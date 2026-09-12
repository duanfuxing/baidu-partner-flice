import json
from types import SimpleNamespace

import pytest

from playwright.sync_api import sync_playwright

from scripts.qualification_trace import NetworkTrace, Redactor
from scripts.trace_qualification_lifecycle import LifecycleRunner


def test_trace_redacts_secrets_and_preserves_cross_request_identity():
    r = Redactor()
    result = r.data({'status': 0, 'token': 'secret-token', 'nested': {
        'Cookie': 'secret-cookie', 'custId': 'customer-123',
        'upload_file': 'file-aaa,file-bbb', 'evidence_url': 'https://example.test/private?token=secret-query',
    }})
    text = json.dumps(result)
    for secret in ('secret-token', 'secret-cookie', 'customer-123', 'file-aaa', 'file-bbb', 'secret-query', '/private'):
        assert secret not in text
    assert result['status'] == 0
    assert result['nested']['upload_file'][0] == r.data({'data': 'file-aaa'})['data']
    assert r.url('https://fkzhunru.baidu.com/permit/web/permit/getlice?filename=file-aaa')['query']['filename'] == result['nested']['upload_file'][0]


def test_trace_multipart_keeps_structure_without_contents():
    raw = (b'--sample\r\nContent-Disposition: form-data; name="token"\r\n\r\nsuper-secret\r\n'
           b'--sample\r\nContent-Disposition: form-data; name="file"; filename="private-name.png"\r\n'
           b'Content-Type: image/png\r\n\r\nprivate-bytes\r\n--sample--\r\n')
    result = Redactor().body('multipart/form-data; boundary=sample', raw)
    text = json.dumps(result)
    assert 'super-secret' not in text
    assert 'private-name' not in text
    assert 'private-bytes' not in text
    assert result[1]['value']['captured_bytes'] == len(b'private-bytes')


def test_trace_closes_even_after_driver_shutdown(tmp_path):
    class ClosedContext:
        def remove_listener(self, *args):
            raise RuntimeError('driver closed')
    trace = NetworkTrace(tmp_path / 'shutdown')
    trace.context = ClosedContext()
    trace.handlers = {'request': lambda: None}
    trace.close()
    trace.close()
    events = [json.loads(x) for x in (tmp_path/'shutdown/events.jsonl').read_text().splitlines()]
    assert events[-1]['kind'] == 'capture_end'


@pytest.mark.parametrize(('allow_writes', 'endpoint', 'expected'), [
    (False, 'geturlinfo', 'continue'),
    (False, 'submitlice', 'abort'),
    (True, 'submitlice', 'continue'),
    (False, 'submitall', 'abort'),
    (True, 'submitall', 'abort'),
])
def test_diagnostic_final_submission_guard(allow_writes, endpoint, expected):
    actions = []
    runner = object.__new__(LifecycleRunner)
    runner.allow_writes = allow_writes
    runner.trace = SimpleNamespace(redactor=Redactor(), emit=lambda *a, **kw: None)
    route = SimpleNamespace(
        request=SimpleNamespace(url=f'https://fkzhunru.baidu.com/permit/web/permit/{endpoint}?token=secret'),
        abort=lambda: actions.append('abort'), continue_=lambda: actions.append('continue'))
    runner.guard(route)
    assert actions == [expected]


def test_local_browser_records_upload_save_and_failures(tmp_path):
    trace = NetworkTrace(tmp_path / 'capture')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context()
        trace.attach(context)
        html = '''<div class="form-card"><input type="file"><input value="private-proof"></div>
        <script>document.querySelector('input[type=file]').onchange=async()=>{
          const upload=await fetch('/permit/web/permit/savelicepic',{method:'POST',
            headers:{'Content-Type':'application/json'},body:JSON.stringify({token:'private-token'})});
          const result=await upload.json();
          await fetch('/permit/web/permit/submitlice',{method:'POST',
            headers:{'Content-Type':'application/json'},body:JSON.stringify({upload_file:result.data})});
          await fetch('/permit/web/permit/fail').catch(()=>{});
          await fetch('/permit/web/permit/unavailable');
          window.done=true;
        };</script>'''
        def route_handler(route):
            path = route.request.url.split('?')[0].rsplit('/', 1)[-1]
            if path == 'fail':
                route.abort('connectionreset')
            elif path == 'unavailable':
                route.fulfill(status=503, json={'status': 9})
            elif path == 'savelicepic':
                route.fulfill(json={'status': 0, 'data': 'test-file-id'})
            elif path == 'submitlice':
                route.fulfill(json={'status': 0})
            else:
                route.fulfill(content_type='text/html', body=html)
        context.route('**/*', route_handler)
        page = context.new_page()
        page.goto('https://fkzhunru.baidu.com/fixture')
        trace.mark('before_first_file')
        for index in range(2):
            page.evaluate('window.done=false')
            page.locator('input[type=file]').set_input_files({'name':f'local-{index}.png','mimeType':'image/png','buffer':b'bytes'})
            page.wait_for_function('window.done===true')
        page.wait_for_timeout(500)
        context.close()
        trace.close()
        browser.close()
    raw = (tmp_path / 'capture/events.jsonl').read_text(encoding='utf-8')
    assert 'private-token' not in raw
    assert 'private-proof' not in raw
    assert 'test-file-id' not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    assert any(e['kind']=='dom_event' and e['data']['event']=='change' for e in events)
    assert any(e['kind']=='snapshot' for e in events)
    assert len([e for e in events if e['kind']=='failed']) == 2
    uploads = [e for e in events if e['kind']=='request' and e['url']['path'].endswith('/savelicepic')]
    assert len(uploads) == 2
    for request in uploads:
        lifecycle = [e['kind'] for e in events if e.get('request_id')==request['request_id']]
        assert lifecycle == ['request','response','finished','response_body']
    assert not any(e['kind']=='capture_error' for e in events)
