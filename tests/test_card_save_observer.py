"""真实本地 Chrome 验证保存全程观察，不连接百度服务器。"""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.card_save import CardSaveObserver, CARD_IDENTITY_JS
from src.errors import AuthenticationRequired, PageFlowError
from src.new_audit_qualification import NewAuditQualificationPage
from src.upload_identity import UploadReceipt
from src.models import Qualification, QualificationType, Expiry

ORIGIN = 'https://fkzhunru.baidu.com'
SAVE = '/permit/web/permit/submitlice'
READ = '/permit/web/permit/geturlinfo?crmid=customer&urlid=url'
IDENTITY = {'crmid': 'customer', 'urlid': 'url', 'tradeid': 'business', 'liceid': 'kind', 'lice_index': 'record'}
PAYLOAD = {**IDENTITY, 'upload_file': 'file-a,file-b', 'evidence_url': 'proof'}
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>'


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel='chrome', headless=True)
        yield b
        b.close()


@pytest.fixture
def setup(browser):
    page = browser.new_page()
    requests = []
    def serve(route):
        if route.request.url.endswith(SAVE):
            requests.append(route.request)
            route.fulfill(json={'status': 0})
        else:
            route.fulfill(body='test')
    page.route('**/*', serve)
    page.goto(ORIGIN + '/test')
    page.set_content('''<section><div class="form-card" style="width:500px;height:200px">
      <input type=file><input id=evidence value=proof></div></section>
      <script>
        window.calls=0;
        window.send=payload=>fetch('/permit/web/permit/submitlice',{
          method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).catch(()=>{});
        const card=document.querySelector('.form-card');
        card.__vueParentComponent={subTree:{el:card},props:{urlId:'url',tradeid:'business',data:{lice_id:'kind'}},
          exposed:{formData:{value:{lice_index:'record'}},handleSubmit:()=>{window.calls++;return window.send(window.payload);}}};
      </script>''')
    page.evaluate('p=>window.payload=p', PAYLOAD)
    view = NewAuditQualificationPage(page, timeout=900)
    receipts = [UploadReceipt(Path(x), 'hash', x) for x in ('file-a', 'file-b')]
    yield page, view, receipts, requests
    page.close()


def save(view, page, receipts, observer, cursor=0):
    return view._save_qualification_card(lambda: page.locator('.form-card'), lambda: page.locator('section'),
        'proof', receipts, 'sample', save_scope=(observer, cursor, page.locator('.form-card').evaluate(CARD_IDENTITY_JS)))


@pytest.mark.parametrize('mode', ['early', 'pending', 'wrong_card', 'partial', 'wrong_evidence', 'stale'])
def test_early_and_pending_saves_are_reused_only_for_matching_card(setup, mode):
    page, view, receipts, requests = setup
    payload = dict(PAYLOAD)
    if mode == 'wrong_card': payload['lice_index'] = 'another-record'
    if mode == 'partial': payload['upload_file'] = 'file-a'
    if mode == 'wrong_evidence': payload['evidence_url'] = 'wrong'
    with CardSaveObserver(page) as observer:
        page.evaluate('p=>{window.send(p)}', payload)
        if mode == 'pending':
            # A delayed server response stays in flight while the save method starts.
            # Use a second pending matching request after a completed first request.
            page.wait_for_timeout(80)
            held=[]
            page.route('**/submitlice', lambda route: held.append(route))
            page.evaluate('p=>{window.send(p)}', payload)
            page.wait_for_timeout(50)
            original=page.wait_for_timeout
            def wait(ms):
                original(ms)
                if held: held.pop().fulfill(json={'status':0})
            page.wait_for_timeout=wait
        else:
            page.wait_for_timeout(120)
        cursor = observer.checkpoint() if mode == 'stale' else 0
        save(view, page, receipts, observer, cursor)
        assert page.evaluate('window.calls') == (0 if mode in ('early','pending') else 1)
        assert observer.state(cursor, {'lice_index':'record'}, receipts, 'proof')[0] == 'saved'


@pytest.mark.parametrize('mode', ['business', 'http', 'auth', 'malformed', 'latest_bad', 'different_noop'])
def test_bad_results_cannot_pass_or_replay_writes(setup, mode):
    page, view, receipts, requests = setup
    with CardSaveObserver(page) as observer:
        if mode == 'latest_bad':
            page.evaluate('p=>window.send(p)', PAYLOAD)
            page.wait_for_timeout(70)
        if mode in ('business', 'latest_bad'):
            page.route('**/submitlice', lambda r:r.fulfill(json={'status':1009,'message':'private-value'}))
        elif mode == 'http': page.route('**/submitlice', lambda r:r.fulfill(status=503,body='busy'))
        elif mode == 'auth': page.route('**/submitlice', lambda r:r.fulfill(status=401,body='private-value'))
        elif mode == 'malformed': page.route('**/submitlice', lambda r:r.fulfill(body='not-json'))
        payload = dict(PAYLOAD)
        if mode == 'different_noop':
            payload['upload_file']='file-a'
            page.evaluate("()=>{document.querySelector('.form-card').__vueParentComponent.exposed.handleSubmit=()=>{window.calls++}}")
        page.evaluate('p=>window.send(p)', payload)
        page.wait_for_timeout(70)
        with pytest.raises(AuthenticationRequired if mode == 'auth' else PageFlowError) as exc:
            save(view, page, receipts, observer)
        assert 'private-value' not in str(exc.value)
        assert page.evaluate('window.calls') == (1 if mode == 'different_noop' else 0)


@pytest.mark.parametrize('mode', ['persisted', 'wrong_files', 'wrong_record', 'wrong_evidence', 'empty', 'null', 'duplicate', 'read_auth', 'unobserved', 'pending',
                                 'mapped_crmid', 'wrong_url_context', 'wrong_mapped_crmid', 'missing_mapping', 'boolean_status'])
def test_unknown_save_reads_only_observed_matching_detail(setup, mode):
    page, view, receipts, requests = setup
    row={**IDENTITY,'filename':'file-a,file-b','evidence_url':'proof'}
    if mode=='wrong_files': row['filename']='file-a'
    if mode=='wrong_record': row['lice_index']='another'
    if mode=='wrong_evidence': row['evidence_url']='wrong'
    body={'status':0,'data':{'trade_lice_info':{'opt':[{'data':[row,row] if mode=='duplicate' else [row]}]}}}
    if mode=='empty': body['data']['trade_lice_info']['opt']=None
    if mode=='null': body['data']['trade_lice_info']=None
    if mode in ('mapped_crmid', 'wrong_url_context', 'wrong_mapped_crmid', 'missing_mapping'):
        row['crmid']='internal-customer'
        if mode!='missing_mapping':
            body['data']['url_info']={'urlid':'another-url' if mode=='wrong_url_context' else 'url',
                                     'crmid':'another-customer' if mode=='wrong_mapped_crmid' else 'internal-customer'}
    if mode=='boolean_status': body['status']=False
    read_count=[]
    def read(route):
        read_count.append(1)
        route.fulfill(status=401 if mode=='read_auth' else 200,json=body)
    page.route('**/geturlinfo?*', read)
    page.route('**/submitlice', lambda r:None if mode=='pending' else r.abort('failed'))
    with CardSaveObserver(page) as observer:
        if mode!='unobserved': page.evaluate('url=>fetch(url).then(r=>r.json())', READ)
        page.evaluate('p=>{window.send(p)}', PAYLOAD)
        page.wait_for_timeout(100)
        if mode in ('persisted','mapped_crmid'):
            save(view,page,receipts,observer)
        else:
            with pytest.raises(AuthenticationRequired if mode=='read_auth' else PageFlowError):
                save(view,page,receipts,observer)
        assert page.evaluate('window.calls')==0
        assert len(read_count)==(0 if mode=='unobserved' else 1 if mode=='pending' else 2)


@pytest.mark.parametrize('fail_at', [None, 2])
def test_entire_multifile_pipeline_observes_save_before_save_method(browser, tmp_path, fail_at):
    page=browser.new_page()
    uploaded=[];saved=[]
    def serve(route):
        url=route.request.url
        if url.endswith('/savelicepic'):
            uploaded.append(1)
            route.fulfill(json={'status':0,'data':f'file-{len(uploaded)}'})
        elif url.endswith('/submitlice'):
            payload=route.request.post_data_json;saved.append(payload)
            route.fulfill(json={'status':1 if len(saved)==fail_at else 0})
        elif '/getlicepic?' in url: route.fulfill(content_type='image/svg+xml',body=SVG)
        else: route.fulfill(body='test')
    page.route('**/*',serve)
    page.goto(ORIGIN+'/test')
    page.set_content('''<section id=business><div class=form-card style="width:500px;height:220px">
      <input type=file><input value=proof><span>已保存待送审</span>
      <div class=preview-container><span class=file-count>0/9</span><div id=files></div></div>
      </div></section><script>
      const card=document.querySelector('.form-card');window.ids=[];window.calls=0;window.dirty=false;
      window.save=async()=>{
        if(!window.dirty)return;window.dirty=false;
        await fetch('/permit/web/permit/submitlice',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({upload_file:ids.join(','),evidence_url:'proof'})});
      };
      card.__vueParentComponent={subTree:{el:card},exposed:{handleSubmit:()=>{window.calls++;return window.save();}}};
      card.querySelector('input[type=file]').onchange=async()=>{
        const r=await fetch('/permit/web/permit/savelicepic',{method:'POST'});const body=await r.json();
        ids.push(body.data);window.dirty=true;
        document.querySelector('#files').insertAdjacentHTML('beforeend','<div class=preview-list-li><img src="/permit/web/permit/getlicepic?filename='+body.data+'"></div>');
        document.querySelector('.file-count').textContent=ids.length+'/9';
        await window.save();
      };
      </script>''')
    paths=[]
    for i in range(3):
        p=tmp_path/f'{i}.jpg';p.write_text(SVG);paths.append(p)
    q=Qualification(index_name='资质1',qualification_no='',qualification_name='',expiry=Expiry(permanent=False),evidence_url='proof',files=tuple(paths))
    view=NewAuditQualificationPage(page,timeout=3000)
    try:
        if fail_at:
            with pytest.raises(PageFlowError,match='自动保存失败'):
                view._upload_type_in(QualificationType('推广审查',(q,)),0,lambda:page.locator('#business'))
        else:
            view._upload_type_in(QualificationType('推广审查',(q,)),0,lambda:page.locator('#business'))
            assert len(view._saved_file_receipts[(0,0)])==3
        assert len(uploaded)==(fail_at or 3)
        assert [p['upload_file'] for p in saved]==[','.join(f'file-{j}' for j in range(1,i+1)) for i in range(1,(fail_at or 3)+1)]
        assert page.evaluate('window.calls')==0
    finally:
        page.close()


def test_later_save_cannot_overwrite_success_during_page_verification(setup):
    page, view, receipts, _ = setup
    with CardSaveObserver(page) as observer:
        page.evaluate('p=>window.send(p)', PAYLOAD)
        page.wait_for_timeout(70)
        save(view, page, receipts, observer)
        page.evaluate('p=>window.send(p)', {**PAYLOAD, 'evidence_url': 'late-wrong'})
        page.wait_for_timeout(70)
        scope = (observer, 0, page.locator('.form-card').evaluate(CARD_IDENTITY_JS))
        with pytest.raises(PageFlowError, match='核验期间保存状态发生变化'):
            view._save_observed_card(lambda: page.locator('.form-card'), 'proof', receipts, 'sample', scope, allow_trigger=False)
        assert page.evaluate('window.calls') == 0
