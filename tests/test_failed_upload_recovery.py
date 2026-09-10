import hashlib
import json
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError
from src.new_audit_qualification import NewAuditQualificationPage
from src.upload_identity import UploadReceipt, preview_files, verify_preview_content
from src.upload_retry import upload_with_retry


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize('mode', ['normal', '404', 'wrong_content', '500', 'business_error', 'exhausted',
                                 'delete_failed', 'extra_item', 'aborted', 'changed_before_delete', 'late_verify', 'late_cleanup'])
def test_failed_current_image_is_removed_before_retry(browser, tmp_path, mode, caplog, monkeypatch):
    caplog.set_level('INFO')
    images = {}
    for name, color in [('saved.png', 'red'), ('new.png', 'blue')]:
        buf = BytesIO()
        Image.new('RGB', (3, 3), color).save(buf, format='PNG')
        images[name] = buf.getvalue()
        (tmp_path/name).write_bytes(buf.getvalue())
    saved = UploadReceipt(tmp_path/'saved.png', hashlib.sha256(images['saved.png']).hexdigest(), 'saved.png')
    page = browser.new_page()
    calls = []
    html = '''<div id="card"><input type="file"><div class="preview-container"><ul></ul></div></div>
    <script>
    window.deleted=[];window.overlapped=false;
    function add(id){const li=document.createElement('li');li.className='preview-list-li';
      li.innerHTML=`<img src="/file?filename=${id}"><button class="delete-btn">删除</button>`;
      li.querySelector('button').onclick=()=>{window.deleted.push(id);if(MODE!=='delete_failed')li.remove();};
      document.querySelector('ul').append(li);}
    add('saved.png');
    document.querySelector('input').onchange=async()=>{
      if(document.querySelectorAll('li').length!==1)window.overlapped=true;
      const r=await fetch('/permit/web/permit/savelicepic',{method:'POST',body:new FormData()});
      const body=await r.json();add(body.data);
      if(MODE==='extra_item')add('unrelated.png');
    };
    </script>'''.replace('MODE', json.dumps(mode))

    def serve(route):
        path = urlsplit(route.request.url).path
        if path.endswith('/savelicepic'):
            calls.append(1)
            if mode == 'aborted': route.abort(); return
            bad = mode == 'exhausted' or (len(calls) == 1 and mode not in ('normal', 'late_verify'))
            route.fulfill(status=500 if mode == '500' and bad else 200,
                          json={'status': 1 if mode in ('500', 'business_error') and bad else 0,
                                'data': 'bad.png' if bad else 'new.png'})
        elif path == '/file':
            name = parse_qs(urlsplit(route.request.url).query)['filename'][0]
            if name == 'saved.png' or name == 'new.png':
                route.fulfill(content_type='image/png', body=images[name])
            elif mode == 'wrong_content':
                route.fulfill(content_type='image/png', body=images['saved.png'])
            else: route.fulfill(status=404)
        else: route.fulfill(content_type='text/html; charset=utf-8', body=html)
    page.route('**/*', serve)
    page.goto('https://fkzhunru.baidu.com/test')
    view = NewAuditQualificationPage(page, timeout=1600)
    card = lambda: page.locator('#card')
    receipts = [saved]
    def trigger():
        page.locator('input').evaluate("e=>e.value=''")
        page.locator('input').set_input_files(str(tmp_path/'new.png'))
    original_verify = verify_preview_content
    changed = False
    def during_cleanup(*args):
        nonlocal changed
        original_verify(*args)
        if not changed and len(args[1]) == 1:
            changed = True
            if mode == 'changed_before_delete':
                page.evaluate("""() => {add('saved.png');const ul=document.querySelector('ul');
                    ul.insertBefore(ul.lastElementChild,ul.children[1]);}""")
            if mode == 'late_cleanup':
                page.evaluate("fetch('/permit/web/permit/savelicepic',{method:'POST'}).then(r=>r.text())")
    if mode in ('changed_before_delete', 'late_cleanup'):
        monkeypatch.setattr('src.new_audit_qualification.verify_preview_content', during_cleanup)
    def verify(responses):
        if mode == 'late_verify':
            page.evaluate("fetch('/permit/web/permit/savelicepic',{method:'POST'}).then(r=>r.text())")
        attempt = receipts + [UploadReceipt.from_response(tmp_path/'new.png', responses[0])]
        verify_preview_content(page, attempt, preview_files(card()), 1200)
        view._verify_file_receipts(card, attempt, '资质1')
    def run():
        return upload_with_retry(page, trigger, lambda:card().locator('li').count(),
            lambda r:view._submitlice_response(r, '测试图片'), description='当前图片', timeout_ms=400,
            verify_success=verify, cleanup_failed=lambda responses, guard:view._remove_failed_upload(
                card, receipts, responses, tmp_path/'new.png', '资质1', guard))
    if mode in ('normal', '404', 'wrong_content', '500', 'business_error'):
        run()
        assert len(calls) == (1 if mode == 'normal' else 2)
        assert [x['id'] for x in preview_files(card())] == ['saved.png', 'new.png']
    else:
        with pytest.raises(PageFlowError): run()
        assert len(calls) == (4 if mode == 'exhausted' else 2 if mode in ('late_verify', 'late_cleanup') else 1)
    assert page.evaluate('window.overlapped') is False
    assert 'saved.png' not in page.evaluate('window.deleted')
    if mode in ('changed_before_delete', 'late_verify', 'late_cleanup'):
        assert page.evaluate('window.deleted') == []
    verify_preview_content(page, receipts, preview_files(card())[:1], 1200)
    if mode == 'exhausted':
        assert page.evaluate('window.deleted') == ['bad.png'] * 4
        assert card().locator('li').count() == 1
    if mode == '404': assert 'HTTP 404' in caplog.text
    assert 'HTTP 200' in caplog.text
    page.close()
