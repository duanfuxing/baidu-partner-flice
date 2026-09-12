"""专用诊断采集器：只写脱敏事件，不保存原始 HAR 或认证数据。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


SECRET = re.compile(r"cookie|token|authorization|password|passwd|secret|credential|bduss|stoken|csrf|ticket|signature|^sign$", re.I)
NUMERIC = re.compile(r"^(status|code|errno|count|total|totalCount|page|pageNo|pageSize|size|length|width|height)$", re.I)


class Redactor:
    def __init__(self):
        self.salt = secrets.token_bytes(32)

    def alias(self, value):
        digest = hmac.new(self.salt, str(value).encode(), hashlib.sha256).hexdigest()[:16]
        return f"ref-{digest}"

    def key(self, value):
        return value if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9.\[\]-]{0,47}", value) else self.alias(value)

    def url(self, value):
        try:
            p = urlsplit(value)
            # Retain endpoint names; redact opaque asset paths and SPA parameters.
            if p.path.startswith('/permit/web/permit/'):
                endpoint = p.path.rsplit('/', 1)[-1]
                path = '/permit/web/permit/' + (endpoint if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,45}', endpoint) else self.alias(endpoint))
            elif p.path.startswith(('/polaris-web/', '/permit/')):
                path = p.path if re.fullmatch(r'[A-Za-z/_-]+', p.path) else self.alias(p.path)
            elif p.path in ('/newaudit', '/flice', '/portal/workbench', '/'):
                path = p.path
            else:
                path = '/' + self.alias(p.path)
            fragment = p.fragment.split('?')[0].split('/')
            route = '/'.join(x if x in ('', 'lice', 'submit', 'invest_lice_list', 'add_invest_lice', 'edit_invest_lice', 'truth') else self.alias(x) for x in fragment)
            return {'host': p.hostname, 'path': path, 'query': self.data(dict(parse_qsl(p.query, keep_blank_values=True))), 'route': route}
        except Exception:
            return {'opaque': self.alias(value)}

    def data(self, value, key='', depth=0):
        if SECRET.search(key):
            return '[REDACTED]'
        if depth > 16:
            return '[DEPTH_LIMIT]'
        if isinstance(value, dict):
            return {self.key(str(k)): self.data(v, str(k), depth + 1) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.data(v, key, depth + 1) for v in value]
        if value is None or isinstance(value, bool) or value == '':
            return value
        if NUMERIC.fullmatch(key) and isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            if value.startswith(('http://', 'https://')):
                return self.url(value)
            if key == 'upload_file':
                return [self.alias(part) for part in value.split(',')]
            if value.startswith(('{', '[')):
                try:
                    return self.data(json.loads(value), key, depth + 1)
                except (ValueError, TypeError):
                    pass
        return self.alias(value)

    def body(self, content_type, raw):
        if not raw:
            return None
        if 'multipart/form-data' in content_type:
            message = BytesParser(policy=policy.default).parsebytes(
                b'Content-Type: ' + content_type.encode() + b'\r\nMIME-Version: 1.0\r\n\r\n' + raw
            )
            fields = []
            for part in message.iter_parts():
                name = part.get_param('name', header='content-disposition') or 'unknown'
                payload = part.get_payload(decode=True) or b''
                if part.get_filename() is not None:
                    # Chromium may omit file bytes from post_data_buffer; never report
                    # an empty captured segment as a zero-byte source file.
                    value = {'file_ref': self.alias(part.get_filename()), 'captured_bytes': len(payload),
                             'binary_capture': 'present' if payload else 'omitted-or-empty',
                             'captured_sha256': hashlib.sha256(payload).hexdigest() if payload else None}
                else:
                    value = self.data(payload.decode('utf-8', errors='replace'), name)
                fields.append({'field': self.key(name), 'value': value})
            return fields
        try:
            text = raw.decode('utf-8')
            if 'json' in content_type or text.startswith(('{', '[')):
                return self.data(json.loads(text))
            if 'application/x-www-form-urlencoded' in content_type:
                return self.data(dict(parse_qsl(text, keep_blank_values=True)))
        except (ValueError, UnicodeError):
            pass
        return {'bytes': len(raw), 'content': '[OMITTED]'}


DOM_OBSERVER = r"""(() => {
  if (location.hostname !== 'fkzhunru.baidu.com' && location.hostname !== '127.0.0.1') return;
  if (window.__bpfTraceInstalled) return;
  window.__bpfTraceInstalled = true;
  const send = (kind, data) => window.__bpfTrace({kind, wall_ms:Date.now(), data}).catch(()=>{});
  const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const statuses = ['已保存待送审','待保存','上传中','上传失败','保存失败','保存成功'];
  const snapshot = () => ({
    cards:[...document.querySelectorAll('input[type=file]')].map((input,index)=>{
      const card=input.closest('.form-card') || input.parentElement;
      return {index, visible:visible(card), selected_count:input.files.length,
        fields:[...card.querySelectorAll('input:not([type=file])')].map(x=>({type:x.type,value:x.value})),
        files:[...card.querySelectorAll('.preview-list-li')].map(x=>{
          const img=x.querySelector('img'), a=x.querySelector('a[href]');
          return {url:img?.src || a?.href || null,ready:!img || (img.complete && img.naturalWidth>0)};
        }),
        status:statuses.filter(s=>(card.textContent || '').includes(s)),
        loading:[...card.querySelectorAll('.el-loading-mask')].filter(visible).length};
    }),
    loading:[...document.querySelectorAll('.el-loading-mask')].filter(visible).length,
    messages:[...document.querySelectorAll('.el-message,.el-notification')].filter(visible).map(x=>x.textContent)
  });
  let last='';
  setInterval(()=>{const value=snapshot(), next=JSON.stringify(value); if(next!==last){last=next;send('snapshot',value);}},250);
  for (const name of ['click','change','input','focusin','focusout','mouseover','mouseout']) {
    document.addEventListener(name,e=>{
      const target=e.target;
      if(!(target instanceof Element))return;
      const card=target.closest('.form-card');
      if ((name==='mouseover'||name==='mouseout') && (!card||card.contains(e.relatedTarget)))return;
      if(!card && name!=='click')return;
      send('dom_event',{event:name,tag:target.tagName,type:target.getAttribute('type'),
        card_index:card?[...document.querySelectorAll('input[type=file]')].findIndex(x=>card.contains(x)):-1,
        selected_count:target instanceof HTMLInputElement && target.type==='file'?target.files.length:undefined,
        label:target.closest('button')?.textContent?.trim() || null,is_trusted:e.isTrusted});
    },true);
  }
})();"""


class NetworkTrace:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.stream = (directory / 'events.jsonl').open('x', encoding='utf-8')
        self.redactor = Redactor()
        self.start = time.monotonic()
        self.requests = {}
        self.responses = {}
        self.pages = {}
        self.phase = 'initialization'
        self.seq = 0
        self.context = None
        self.handlers = {}
        self.cdp_sessions = []

    def emit(self, kind, **safe_data):
        self.seq += 1
        row = {'seq': self.seq, 'elapsed_ms': round((time.monotonic()-self.start)*1000, 2),
               'wall_ms': int(time.time()*1000), 'phase': self.phase, 'kind': kind, **safe_data}
        self.stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.stream.flush()

    def mark(self, phase):
        self.phase = phase
        self.emit('action', name=phase)
        print('TRACE_PHASE', phase, flush=True)

    def page_id(self, page):
        if page is None:
            return None
        return self.pages.setdefault(page, f'p{len(self.pages)+1}')

    def attach(self, context):
        self.context = context
        context.expose_binding('__bpfTrace', self._dom)
        context.add_init_script(script=DOM_OBSERVER)
        self.handlers = {'request': self._request, 'response': self._response,
                         'requestfinished': self._finished, 'requestfailed': self._failed,
                         'page': self._page}
        for name, handler in self.handlers.items():
            context.on(name, handler)
        for page in context.pages:
            self._page(page)
            page.evaluate(DOM_OBSERVER)

    def _dom(self, source, value):
        # Field values and free text are redacted; structural numeric state is preserved.
        data = value.get('data', {})
        if value.get('kind') == 'snapshot':
            for card in data.get('cards', []):
                card['fields'] = [{'type': x['type'], 'value': self.redactor.data(x['value'])} for x in card['fields']]
                for file in card.get('files', []):
                    file['url'] = self.redactor.url(file['url']) if file['url'] else None
            data['messages'] = self.redactor.data(data.get('messages', []))
        else:
            data['label'] = self.redactor.data(data.get('label'))
        self.emit(value.get('kind', 'dom'), page=self.page_id(source['page']), browser_wall_ms=value.get('wall_ms'), data=data)

    def _page(self, page):
        self.emit('page', page=self.page_id(page))
        page.on('framenavigated', lambda frame: self.emit('navigation', page=self.page_id(page), url=self.redactor.url(frame.url)))
        page.on('pageerror', lambda error: self.emit('pageerror', page=self.page_id(page), error_ref=self.redactor.alias(str(error))))
        try:
            cdp = self.context.new_cdp_session(page)
            cdp.send('Network.enable')
            self.cdp_sessions.append(cdp)
            def initiated(value):
                request = value['request']
                stack = value.get('initiator', {}).get('stack', {})
                frames = []
                for _ in range(5):
                    frames.extend({'function': frame.get('functionName', ''),
                                   'script': self.redactor.url(frame.get('url', '')),
                                   'line': frame.get('lineNumber'), 'column': frame.get('columnNumber')}
                                  for frame in stack.get('callFrames', []))
                    stack = stack.get('parent', {})
                    if not stack:
                        break
                self.emit('cdp_request', page=self.page_id(page), cdp_request_id=value['requestId'],
                          url_ref=self.redactor.alias(request['url']), url=self.redactor.url(request['url']),
                          method=request['method'], browser_wall_ms=value.get('wallTime', 0)*1000,
                          initiator_type=value.get('initiator', {}).get('type'), stack=frames)
            cdp.on('Network.requestWillBeSent', initiated)
            cdp.on('Network.responseReceived', lambda value: self.emit('cdp_response',
                page=self.page_id(page), cdp_request_id=value['requestId'],
                status=value['response']['status'], timing=value['response'].get('timing'),
                from_disk_cache=value['response'].get('fromDiskCache', False),
                from_service_worker=value['response'].get('fromServiceWorker', False)))
            cdp.on('Network.webSocketCreated', lambda value: self.emit('websocket', page=self.page_id(page),
                cdp_request_id=value['requestId'], url=self.redactor.url(value['url'])))
        except Exception as exc:
            self.emit('cdp_unavailable', page=self.page_id(page), error_type=type(exc).__name__)

    def _request(self, request):
        rid = f'r{len(self.requests)+1}'
        self.requests[request] = (rid, time.monotonic())
        try:
            page = request.frame.page
        except Exception:
            page = None
        fields = {'request_id': rid, 'page': self.page_id(page), 'method': request.method,
                  'resource_type': request.resource_type, 'url': self.redactor.url(request.url),
                  'url_ref': self.redactor.alias(request.url)}
        # Use cached content type only. Never persist request headers.
        content_type = request.headers.get('content-type', '')
        if request.resource_type in ('xhr', 'fetch'):
            fields['body'] = self.redactor.body(content_type, request.post_data_buffer)
        if request.redirected_from in self.requests:
            fields['redirected_from'] = self.requests[request.redirected_from][0]
        self.emit('request', **fields)

    def _response(self, response):
        request = response.request
        self.responses[request] = response
        self.emit('response', request_id=self.requests.get(request, (None,))[0], status=response.status)

    def _finished(self, request):
        rid, start = self.requests.get(request, (None, time.monotonic()))
        self.emit('finished', request_id=rid, duration_ms=round((time.monotonic()-start)*1000, 2))
        response = self.responses.get(request)
        if response is None or request.resource_type not in ('xhr', 'fetch'):
            return
        try:
            content_type = response.headers.get('content-type', '')
            if 'json' in content_type:
                raw = response.body()
                self.emit('response_body', request_id=rid, body=self.redactor.body(content_type, raw))
        except Exception as exc:
            self.emit('capture_error', request_id=rid, error_type=type(exc).__name__)

    def _failed(self, request):
        reason = request.failure or ''
        match = re.search(r'net::ERR_[A-Z_]+', reason)
        self.emit('failed', request_id=self.requests.get(request, (None,))[0],
                  reason=match.group() if match else self.redactor.alias(reason))

    def close(self):
        if self.stream.closed:
            return
        if self.context:
            for name, handler in self.handlers.items():
                try:
                    self.context.remove_listener(name, handler)
                except Exception:
                    # The dedicated BrowserSession may already have closed its driver.
                    pass
        self.emit('capture_end')
        self.stream.close()
