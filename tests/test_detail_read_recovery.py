"""页面详情读取恢复：只使用本机 HTTP 服务，不连接百度。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import sync_playwright, Error as PlaywrightError

from src.detail_read_recovery import DetailReadRecovery, DETAIL_PATTERN
from src.errors import AuthenticationRequired, PageFlowError


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b=p.chromium.launch(channel='chrome',headless=True)
        yield b
        b.close()


@pytest.mark.parametrize('mode',['normal','1009','always_1009','503','401','403','other_business','invalid_json','network_once','network_always'])
def test_only_retryable_detail_reads_are_replayed_and_rendered(browser,mode):
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            seen.append(self.path)
            status=503 if mode=='503' and len(seen)==1 else int(mode) if mode in ('401','403') else 200
            code=1009 if mode=='always_1009' or mode=='1009' and len(seen)==1 else 1008 if mode=='other_business' else 0
            body=b'not-json' if mode=='invalid_json' else json.dumps({'status':code,'data':{'files':3}}).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    page=browser.new_page();page.route('**/*',lambda r:r.fulfill(body='test'));page.goto('https://fkzhunru.baidu.com/test')
    recovery=DetailReadRecovery(page,3000)
    calls=[]
    class LocalRoute:
        def __init__(self,route):self.route=route;self.request=route.request
        def fetch(self,**kwargs):
            calls.append(kwargs)
            if mode=='network_always' or mode=='network_once' and len(calls)==1:raise PlaywrightError('test failure')
            return self.route.fetch(url=f'http://127.0.0.1:{server.server_port}/detail',**kwargs)
        def fulfill(self,**kwargs):return self.route.fulfill(**kwargs)
        def abort(self,*args):return self.route.abort(*args)
        def fallback(self):return self.route.fallback()
    page.route(DETAIL_PATTERN,lambda r:recovery.handle(LocalRoute(r)))
    page.set_content('''<button onclick="read()">读取</button><main></main><script>
      window.done=false;window.result=null;
      async function read(){try{const r=await fetch('/permit/web/permit/geturlinfo?crmid=test&token=test-placeholder');
        const b=await r.json();window.result={http:r.status,status:b.status};
        if(r.status===200&&b.status===0)document.querySelector('main').innerHTML='<div class=form-card>3 files</div>';
      }catch(e){}finally{window.done=true;}}
      </script>''')
    try:
        page.get_by_role('button').click();page.wait_for_function('window.done',timeout=5000)
        assert len(calls)==(2 if mode in ('1009','always_1009','503','network_once','network_always') else 1)
        assert all(c=={'timeout':1000,'max_redirects':0,'max_retries':0} for c in calls)
        assert page.locator('.form-card').count()==(1 if mode in ('normal','1009','503','network_once') else 0)
        assert recovery.pending==0
        if mode in ('401','403'):
            with pytest.raises(AuthenticationRequired):recovery.raise_if_failed()
        elif mode in ('always_1009','other_business','invalid_json','network_always'):
            with pytest.raises(PageFlowError):recovery.raise_if_failed()
        else:recovery.raise_if_failed()
    finally:
        page.close();server.shutdown();server.server_close();thread.join()


@pytest.mark.parametrize('url,method',[
    ('https://fkzhunru.baidu.com/permit/web/permit/submitlice','POST'),
    ('https://fkzhunru.baidu.com/permit/web/permit/geturlinfo','POST'),
    ('https://example.test/permit/web/permit/geturlinfo','GET'),
    ('https://fkzhunru.baidu.com/permit/web/permit/geturlinfo/other','GET')])
def test_other_requests_are_never_replayed(url,method):
    from unittest.mock import Mock
    page=Mock();route=Mock();route.request.url=url;route.request.method=method
    DetailReadRecovery(page,3000).handle(route)
    route.fetch.assert_not_called();route.fulfill.assert_not_called();route.fallback.assert_called_once()
