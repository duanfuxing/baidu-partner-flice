"""保存全程观察：关联本卡文件集合，未知结果只读核对，不重放写入。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .errors import AuthenticationRequired, PageFlowError

SAVE_PATH = '/permit/web/permit/submitlice'
READ_PATHS = {'/permit/web/permit/geturlinfo', '/permit/web/permit/geturlandproductinfo'}
IDENTITY_KEYS = ('crmid', 'urlid', 'tradeid', 'liceid', 'licetype', 'lice_index', 'licemap_id')

CARD_IDENTITY_JS = r"""element => {
  const candidates=new Set(), consider=c=>{
    const root=c?.subTree?.el;
    if ((root===element || (root?.classList?.contains('drag-upload-wrapper') &&
         root.querySelectorAll('.form-card').length===1 && root.querySelector('.form-card')===element)) &&
        typeof c.exposed?.handleSubmit==='function') candidates.add(c);
  };
  for(let c=element.__vueParentComponent;c;c=c.parent)consider(c);
  let root=element;while(root&&!root._vnode)root=root.parentElement;
  const seen=new Set(),walk=v=>{
    if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
    if(v.component){consider(v.component);walk(v.component.subTree);}
    if(Array.isArray(v.children))v.children.forEach(walk);
    if(v.suspense)walk(v.suspense.activeBranch);
  };walk(root?._vnode);
  if(candidates.size!==1)return {};
  const c=[...candidates][0],p=c.props||{},f=c.exposed.formData?.value||c.exposed.formData||{};
  const values={urlid:p.urlId,tradeid:p.tradeid,liceid:p.data?.lice_id||p.data?.liceid,
    licetype:p.liceType,lice_index:f.lice_index,licemap_id:p.data?.licemap_id||f.licemap_id};
  return Object.fromEntries(Object.entries(values).filter(([k,v])=>v!==undefined&&v!==null&&v!==''&&String(v)!=='0')
    .map(([k,v])=>[k,String(v)]));
}"""


def request_payload(request):
    try:
        payload = request.post_data_json
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {k: v[-1] for k, v in parse_qs(request.post_data or '', keep_blank_values=True).items()}
    return payload


def identity_matches(payload, identity):
    return all(str(payload.get(k, '')) == str(v) for k, v in identity.items())


@dataclass
class SaveEvent:
    request: object
    payload: dict
    response: object = None
    finished: bool = False
    failed: bool = False


class CardSaveObserver:
    def __init__(self, page):
        self.page = page
        self.events: list[SaveEvent] = []
        self.by_request = {}
        self.read_urls = []
        self.handlers = {'request': self._request, 'response': self._response,
                         'requestfinished': self._finished, 'requestfailed': self._failed}

    def __enter__(self):
        for name, handler in self.handlers.items():
            self.page.on(name, handler)
        return self

    def __exit__(self, *args):
        for name, handler in self.handlers.items():
            self.page.remove_listener(name, handler)

    def checkpoint(self):
        return len(self.events)

    def _request(self, request):
        p = urlsplit(request.url)
        if p.scheme != 'https' or p.hostname != 'fkzhunru.baidu.com':
            return
        if p.path in READ_PATHS and request.method == 'GET':
            self.read_urls.append(request.url)
        if p.path == SAVE_PATH and request.method == 'POST':
            raw = request_payload(request)
            # Keep only matching fields; never retain credential/header values here.
            payload = {k: raw[k] for k in (*IDENTITY_KEYS, 'upload_file', 'evidence_url') if k in raw}
            event = SaveEvent(request, payload)
            self.events.append(event)
            self.by_request[request] = event

    def _response(self, response):
        if response.request in self.by_request:
            self.by_request[response.request].response = response

    def _finished(self, request):
        if request in self.by_request:
            self.by_request[request].finished = True

    def _failed(self, request):
        if request in self.by_request:
            self.by_request[request].failed = True

    def related(self, cursor, identity, receipts):
        ids = {r.server_id for r in receipts}
        result = []
        for event in self.events[cursor:]:
            if not identity_matches(event.payload, identity):
                continue
            files = set(str(event.payload.get('upload_file', '')).split(',')) - {''}
            # Semantic card identity lets us also wait for an older cumulative save.
            if identity or not receipts or files.intersection(ids):
                result.append(event)
        return result

    def state(self, cursor, identity, receipts, evidence):
        events = self.related(cursor, identity, receipts)
        if any(not e.finished and not e.failed for e in events):
            return 'pending', None
        if not events:
            return 'absent', None
        latest = events[-1]
        expected = ','.join(r.server_id for r in receipts)
        exact_files = not receipts or latest.payload.get('upload_file') == expected
        exact_evidence = (latest.payload.get('evidence_url') or '').strip() == evidence
        if latest.failed:
            return 'unknown', latest
        response = latest.response
        if response is None:
            return 'unknown', latest
        if response.status in (401, 403):
            raise AuthenticationRequired(f'资质保存接口未授权（HTTP {response.status}），请重新登录')
        if response.status != 200:
            raise PageFlowError(f'资质自动保存接口 HTTP {response.status}，未重复保存')
        try:
            body = response.json()
        except Exception:
            raise PageFlowError('资质自动保存接口返回非 JSON，未重复保存') from None
        if not isinstance(body, dict) or type(body.get('status')) is not int:
            raise PageFlowError('资质自动保存接口响应结构异常，未重复保存')
        if body['status'] != 0:
            raise PageFlowError(f"资质自动保存失败（status={body['status']}），未重复保存")
        # Reading a response pumps Playwright events. Recheck if another save arrived.
        if self.related(cursor, identity, receipts) != events:
            return 'pending', None
        # No-file fixtures still require an explicit successful request after activation.
        if exact_files and (exact_evidence or not receipts):
            return 'saved', latest
        return 'different', latest

    def readback(self, cursor, identity, receipts, evidence, timeout):
        """只重用已观察到且上下文匹配的详情 GET；写入未结束时不能读回放行。"""
        events = self.related(cursor, identity, receipts)
        if not receipts or not events or any(not e.finished and not e.failed for e in events):
            return False
        payload = events[-1].payload
        if not all(payload.get(k) for k in ('crmid', 'urlid', 'tradeid', 'liceid')):
            return False
        candidates = []
        for url in reversed(self.read_urls):
            query = parse_qs(urlsplit(url).query)
            if all(query.get(k) == [str(payload[k])] for k in ('crmid', 'urlid')) and url not in candidates:
                candidates.append(url)
        expected = ','.join(r.server_id for r in receipts)
        version = len(self.events)
        for url in candidates[:2]:
            try:
                result = self.page.evaluate('''async ({url,timeout})=>{
                  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
                  try{const r=await fetch(url,{cache:'no-store',signal:controller.signal});
                    return {http:r.status,body:await r.json()};}finally{clearTimeout(timer);}
                }''', {'url': url, 'timeout': min(timeout, 5000)})
            except Exception:
                continue
            if result['http'] in (401, 403):
                raise AuthenticationRequired('资质详情核对未授权，请重新登录')
            body = result.get('body')
            if (result['http'] != 200 or not isinstance(body, dict)
                    or type(body.get('status')) is not int or body['status'] != 0):
                continue
            data = body.get('data')
            trade = data.get('trade_lice_info') if isinstance(data, dict) else None
            groups = trade.get('opt') if isinstance(trade, dict) else None
            if not isinstance(groups, list):
                continue
            record_identity = {k: payload[k] for k in IDENTITY_KEYS if payload.get(k) not in (None, '')}
            # 首次创建时这两项可能为0；服务端随后生成真实记录ID。
            for key in ('lice_index', 'licemap_id'):
                if str(record_identity.get(key)) == '0':
                    record_identity.pop(key)
            # 百度请求中的 crmid 与持久化记录中的内部 crmid 不一定相同。
            # 只通过同一详情响应的 URL 主记录建立映射，不无条件忽略公司身份。
            url_info = data.get('url_info')
            if (isinstance(url_info, dict) and url_info.get('crmid') not in (None, '')
                    and str(url_info.get('urlid', '')) == str(payload['urlid'])):
                record_identity['crmid'] = url_info['crmid']
            matches = []
            for group in groups:
                rows = group.get('data') if isinstance(group, dict) else None
                for item in rows if isinstance(rows, list) else []:
                    if (isinstance(item, dict) and item.get('filename') == expected
                            and (item.get('evidence_url') or '').strip() == evidence
                            and identity_matches(item, record_identity)):
                        matches.append(item)
            # Any new save arriving during the read makes this snapshot insufficient.
            if len(matches) == 1 and len(self.events) == version:
                return True
        return False
