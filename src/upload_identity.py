"""关联本地文件与上传凭据；仅在当前资质卡范围内验证，不全局跳过文件。"""

from dataclasses import dataclass
import hashlib
import base64
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .errors import PageFlowError


@dataclass(frozen=True)
class UploadReceipt:
    path: Path
    sha256: str
    server_id: str

    @classmethod
    def from_response(cls, path: Path, response):
        payload = response.json()
        identifier = payload.get("data") if isinstance(payload, dict) else None
        if (response.status != 200 or not isinstance(payload, dict) or payload.get("status") != 0
                or not isinstance(identifier, str) or not identifier.strip()):
            raise PageFlowError("上传接口缺少成功文件标识，停止，不重复上传")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return cls(path.resolve(), digest, identifier)


def verify_file_identities(receipts, actual_ids, *, description):
    expected = [receipt.server_id for receipt in receipts]
    # 不同本地内容不能被同一个服务端文件标识替代。
    identities = {}
    for receipt in receipts:
        previous = identities.setdefault(receipt.server_id, receipt.sha256)
        if previous != receipt.sha256:
            raise PageFlowError(f"{description}：不同源文件返回同一文件标识，停止，不重复上传")
    if actual_ids != expected:
        raise PageFlowError(f"{description}：页面文件身份与上传凭据不一致，存在重复、缺失或顺序错配")


def preview_files(card):
    """读取已渲染的真实预览 URL；PDF 从同一预览组件的公开 props 读取。"""
    return card.locator('.preview-list-li').evaluate_all("""items => items.map((item, index) => {
        const img = item.querySelector('img');
        const link = item.querySelector('a[href]');
        let url = img?.getAttribute('src') || link?.getAttribute('href');
        if (!url) {
            // FilePreview 的图片之外的文件没有 href，但 props.filelist 保存相同 URL。
            for (let node = item; node && !url; node = node.parentElement) {
                for (let c = node.__vueParentComponent; c && !url; c = c.parent) {
                    const files = c.props?.filelist;
                    if (Array.isArray(files)) url = files[index]?.url;
                }
            }
        }
        if (!url) return {id: null, url: null, ready: false};
        const parsed = new URL(url, document.baseURI);
        return {id: parsed.searchParams.get('filename'), url: parsed.href,
                ready: !img || (img.complete && img.naturalWidth > 0)};
    })""")


def saved_request_payload(response):
    try:
        payload = response.request.post_data_json
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {key: values[-1] for key, values in
                   parse_qs(response.request.post_data or '', keep_blank_values=True).items()}
    return payload


def saved_request_has_files(response, receipts):
    payload = saved_request_payload(response)
    return payload.get('upload_file') == ','.join(item.server_id for item in receipts)


def verify_saved_request(response, receipts, evidence):
    """检查页面实际发出的保存内容；不构造或输出动态请求参数。"""
    payload = saved_request_payload(response)
    value = payload.get('upload_file')
    if not isinstance(value, str):
        raise PageFlowError('保存请求缺少文件身份，停止当前公司')
    verify_file_identities(receipts, value.split(','), description='保存请求')
    if (payload.get('evidence_url') or '').strip() != evidence:
        raise PageFlowError('保存请求中的举证链接与输入不一致，停止当前公司')


def verify_preview_content(page, receipts, files, timeout):
    """读取页面已使用的文件 URL，核对原始内容；不使用 URL 相同证明内容相同。"""
    verify_file_identities(receipts, [item['id'] for item in files], description='文件内容核验')
    for receipt, item in zip(receipts, files):
        parsed = urlsplit(item['url'])
        if parsed.scheme not in ('https', 'http') or parsed.hostname != 'fkzhunru.baidu.com':
            raise PageFlowError('无法安全识别资质预览来源，停止文件内容核验')
        try:
            result = page.evaluate("""async ({url, timeout}) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeout);
                try {
                    const response = await fetch(url, {cache:'no-store', signal:controller.signal});
                    if (response.status !== 200) return null;
                    const bytes = new Uint8Array(await response.arrayBuffer());
                    let binary = '';
                    for (let i=0; i<bytes.length; i+=8192)
                        binary += String.fromCharCode(...bytes.subarray(i, i+8192));
                    return btoa(binary);
                } finally {clearTimeout(timer);}
            }""", {'url': item['url'], 'timeout': timeout})
            if result is None:
                raise ValueError('file unavailable')
            actual = hashlib.sha256(base64.b64decode(result)).hexdigest()
        except Exception:
            raise PageFlowError(f'文件“{receipt.path.name}”预览读取失败，停止，不重复上传') from None
        if actual != receipt.sha256:
            raise PageFlowError(f'文件“{receipt.path.name}”服务端内容与原始文件不同，存在覆盖或转换，停止，不重复上传')
