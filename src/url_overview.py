"""监听页面触发的URL查询响应，并核对响应对应的表格。"""

import logging
import time
from urllib.parse import parse_qs, urlsplit

from .errors import AuthenticationRequired, PageFlowError

LOGGER = logging.getLogger(__name__)

_READY = """root => {
    const visible = e => !!e.getClientRects().length;
    if ([...root.querySelectorAll('.el-skeleton, .el-skeleton__item, .el-loading-mask')]
        .some(visible)) return false;
    return [...root.querySelectorAll('tbody tr a[href], .el-table__empty-block')].some(visible);
}"""


def _matches_query(request, target_url):
    try:
        parsed = urlsplit(request.url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        return (parsed.scheme in {'https', 'http'}
                and parsed.hostname == 'fkzhunru.baidu.com'
                and parsed.path == '/permit/web/permit/geturllist'
                and request.method == 'GET'
                and query.get('url', ['']) == [target_url]
                and query.get('page_num') == ['1'])
    except (ValueError, AttributeError):
        return False


def _query_data(response):
    if response.status in (401, 403):
        raise AuthenticationRequired(f'URL查询接口未授权（HTTP {response.status}），请重新登录')
    if response.status != 200:
        raise PageFlowError(f'URL查询接口 HTTP {response.status}，停止，不使用旧结果')
    try:
        payload = response.json()
    except Exception:
        raise PageFlowError('URL查询接口返回非JSON，停止，不使用旧结果') from None
    if not isinstance(payload, dict) or type(payload.get('status')) is not int:
        raise PageFlowError('URL查询接口响应结构异常，停止，不使用旧结果')
    if payload['status'] != 0:
        # 服务端 message 可能回显带认证参数的URL，只记录业务状态码。
        raise PageFlowError(f"URL查询接口业务失败（status={payload['status']}），停止，不使用旧结果")
    data = payload.get('data')
    if (not isinstance(data, dict) or type(data.get('count')) is not int
            or not isinstance(data.get('list'), list) or data['count'] < len(data['list'])
            or any(not isinstance(row, dict) or not isinstance(row.get('url'), str)
                   or not row['url'] or type(row.get('urlid')) not in (int, str)
                   or not str(row['urlid']).strip() for row in data['list'])):
        raise PageFlowError('URL查询接口结果结构异常，停止，不使用旧结果')
    return data


def _query_and_wait(page, region, button, timeout, target_url):
    """先监听本轮页面GET请求，再校验响应及对应表格，绝不自行构造请求。"""
    requests, responses, finished, failed = [], {}, set(), set()

    def on_request(request):
        if _matches_query(request, target_url):
            requests.append(request)

    def on_response(response):
        if response.request in requests:
            responses[response.request] = response

    def on_finished(request):
        if request in requests:
            finished.add(request)

    def on_failed(request):
        if request in requests:
            failed.add(request)

    handlers = {'request': on_request, 'response': on_response,
                'requestfinished': on_finished, 'requestfailed': on_failed}
    for event, handler in handlers.items():
        page.on(event, handler)
    try:
        button.click(timeout=timeout)
        started = time.monotonic()
        deadline, next_log = started + timeout / 1000, started + 10
        while True:
            if len(requests) > 1:
                raise PageFlowError('本轮出现多个URL查询请求，无法确定结果归属，停止，不使用旧结果')
            if failed:
                raise PageFlowError('URL查询接口网络请求失败，停止，不使用旧结果')
            if requests and requests[0] in finished and requests[0] in responses:
                data = _query_data(responses[requests[0]])
                break
            now = time.monotonic()
            if now >= deadline:
                reason = '请求已发出但未完整返回' if requests else '未检测到本轮匹配请求'
                raise PageFlowError(f'等待URL查询接口超时：{reason}，停止，不使用旧结果')
            if now >= next_log:
                LOGGER.info('URL列表：等待geturllist，已等待%.0f秒（%s）',
                            now - started, '请求已发出' if requests else '尚未检测到匹配请求')
                next_log = now + 10
            page.wait_for_timeout(100)
        LOGGER.info('URL列表：geturllist成功（HTTP 200，status=0），共%s条，等待页面回填', data['count'])
        # 直接核对响应的URL和URL ID，既允许相同结果不重建DOM，也不误用旧行。
        expected = [{'url': row['url'], 'id': str(row['urlid'])} for row in data['list']]
        page.wait_for_function("""({root, expected}) => {
            const visible = e => !!e.getClientRects().length;
            const loading = [...root.querySelectorAll('.el-skeleton, .el-skeleton__item, .el-loading-mask')].some(visible);
            const rows = [...root.querySelectorAll('tbody tr')].filter(row =>
              visible(row) && [...row.querySelectorAll('a[href]')].some(visible));
            const matches = !loading && rows.length === expected.length && expected.every((item, index) => {
              const row = rows[index];
              return [...row.querySelectorAll('a[href]')].some(a => visible(a) && a.textContent.trim() === item.url)
                && [...row.querySelectorAll('td')].some(td => td.textContent.trim() === item.id);
            }) && (expected.length || [...root.querySelectorAll('.el-table__empty-block')].some(visible));
            if (!matches) { delete root.__urlSearchStableSince; return false; }
            root.__urlSearchStableSince ??= performance.now();
            return performance.now() - root.__urlSearchStableSince >= 200;
        }""", arg={'root': region.element_handle(), 'expected': expected}, timeout=timeout)
        if len(requests) != 1 or failed:
            raise PageFlowError('页面回填期间URL查询请求发生变化，停止，不使用旧结果')
        return data
    except (AuthenticationRequired, PageFlowError):
        raise
    except Exception:
        raise PageFlowError('URL查询操作或响应对应的表格回填超时，停止，不使用旧结果') from None
    finally:
        for event, handler in handlers.items():
            page.remove_listener(event, handler)
        try:
            region.evaluate('root => { delete root.__urlSearchStableSince; }')
        except Exception:
            pass  # 页面已关闭时不覆盖原始错误。


def search_url_overview(page, target_url: str, timeout: int) -> bool:
    regions = page.locator('.url-overview').filter(has_text='URL状态概览')
    regions = [regions.nth(i) for i in range(regions.count()) if regions.nth(i).is_visible()]
    if not regions:
        return False  # 旧页面保留原分页兼容。
    if len(regions) != 1:
        raise PageFlowError('URL搜索区域不唯一，停止匹配')
    region = regions[0]
    search = region.get_by_placeholder('请输入要查询的url链接', exact=True)
    query = region.get_by_role('button', name='查询', exact=True)
    if search.count() != 1 or query.count() != 1:
        raise PageFlowError('URL搜索控件不完整或不唯一，停止匹配')
    try:
        page.wait_for_function(_READY, arg=region.element_handle(), timeout=timeout)
    except Exception:
        raise PageFlowError('等待URL列表初始数据加载超时，尚未执行搜索') from None

    # 正常页面直接查询；仅已有其他筛选时才重置，避免多发一次页面查询。
    url_id = region.get_by_placeholder('请输入要查询的urlid', exact=True)
    status = region.locator('.el-form-item').filter(has_text='审核状态').locator(
        '.el-select__selected-item:not(.is-transparent):not(.el-select__placeholder)')
    has_status = any(text.strip() and '请选择' not in text for text in status.all_inner_texts())
    if (url_id.count() and url_id.input_value().strip()) or has_status:
        reset = region.get_by_role('button', name='重置', exact=True)
        if reset.count() != 1:
            raise PageFlowError('URL列表有其他筛选但无法重置，停止匹配')
        _query_and_wait(page, region, reset, timeout, '')
    LOGGER.info('URL列表：输入目标链接并点击查询')
    search.fill(target_url, timeout=timeout)
    data = _query_and_wait(page, region, query, timeout, target_url)
    if data['count'] > len(data['list']):
        raise PageFlowError('URL搜索结果超过一页，无法确认目标唯一，请检查输入链接')
    next_page = region.locator('.el-pagination .btn-next')
    if any(next_page.nth(i).is_visible() and next_page.nth(i).is_enabled()
           and 'disabled' not in (next_page.nth(i).get_attribute('class') or '')
           for i in range(next_page.count())):
        raise PageFlowError('URL搜索结果超过一页，无法确认目标唯一，请检查输入链接')
    LOGGER.info('URL列表：搜索表格已刷新，开始精确匹配')
    return True
