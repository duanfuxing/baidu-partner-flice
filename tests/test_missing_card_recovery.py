"""保存200、详情200但卡片丢失：通过只读核对和页面原生刷新恢复。"""
from pathlib import Path
import json
import pytest
from playwright.sync_api import sync_playwright
from src.card_save import CardSaveObserver
from src.errors import PageFlowError
from src.new_audit_qualification import NewAuditQualificationPage
from src.upload_identity import UploadReceipt
from src.models import Qualification, QualificationType, Expiry

@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b=p.chromium.launch(channel='chrome',headless=True)
        yield b
        b.close()

@pytest.mark.parametrize('mode',['recover','zero_create_id','wrong_read','no_callback','wrong_refresh','pending_write','normal','pipeline'])
def test_missing_card_recovery_uses_only_native_read(browser,mode,tmp_path):
    page=browser.new_page();saves=[];reads=[];uploads=[]
    svg='<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>'
    identity={'crmid':'customer','urlid':'url','tradeid':'trade','liceid':'2','licetype':4,'lice_index':'record','licemap_id':'map'}
    payload={**identity,'upload_file':'file-a','evidence_url':'proof'}
    if mode=='zero_create_id':payload.update(lice_index=0,licemap_id=0)
    row={**identity,'filename':'file-a','evidence_url':'proof'}
    def serve(route):
        if '/savelicepic' in route.request.url:
            uploads.append(1);route.fulfill(json={'status':0,'data':'file-a'})
        elif '/submitlice' in route.request.url:
            saves.append(route.request.post_data_json);route.fulfill(json={'status':0})
        elif '/geturlinfo?' in route.request.url:
            reads.append(route.request.url)
            data={**row}
            if mode=='wrong_read' and len(reads)>1:data['filename']='wrong'
            if mode=='wrong_refresh' and len(reads)>2:data['filename']='wrong'
            route.fulfill(json={'status':0,'data':{'trade_lice_info':{'opt':[{'data':[data] if len(reads)>1 else []}]}}})
        elif '/preview?' in route.request.url:
            route.fulfill(content_type='image/svg+xml',body=svg)
        else:route.fulfill(body='test')
    page.route('**/*',serve);page.goto('https://fkzhunru.baidu.com/test')
    view=NewAuditQualificationPage(page,timeout=4300)
    # 显式夹具响应；原生GET恢复层另有本机HTTP服务测试。
    page.route('**/geturlinfo?*',serve)
    page.set_content('''<section id=business class=business-form-card><h2>业务1</h2>
      <div class=form-card id=card><input type=file><input value=proof><span>已保存待送审</span>
        <div class=preview-container><span class=file-count>1/9</span><div class=preview-list-li><img src="/preview?filename=file-a"></div></div>
      </div></section><script>
      const business=document.querySelector('#business'), card=document.querySelector('#card');
      const template=card.outerHTML;window.refreshes=0;
      const read=()=>fetch('/permit/web/permit/geturlinfo?crmid=customer&urlid=url').then(r=>r.json());
      business.__vueParentComponent={type:{__name:'BusinessFormCard'},subTree:{el:business},vnode:{props:{onInit:async()=>{
        window.refreshes++;const body=await read();business.innerHTML=template;
        document.querySelector('img').src='/preview?filename='+body.data.trade_lice_info.opt[0].data[0].filename;}}}};
      card.__vueParentComponent={subTree:{el:card},exposed:{handleSubmit:async()=>{
        const result=await fetch('/permit/web/permit/submitlice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(PAYLOAD)});
        await result.json();await read();if(MODE!=='normal')card.remove();}}};
      </script>'''.replace('PAYLOAD',json.dumps(payload)).replace('MODE',json.dumps(mode)))
    if mode=='no_callback':page.locator('#business').evaluate('e=>delete e.__vueParentComponent.vnode.props.onInit')
    try:
        if mode=='pipeline':
            page.evaluate('''() => {
              const image=document.querySelector('.preview-list-li').outerHTML;
              document.querySelector('.preview-list-li').remove();
              document.querySelector('.file-count').textContent='0/9';
              document.querySelector('input[type=file]').onchange=async()=>{
                await fetch('/permit/web/permit/savelicepic',{method:'POST'});
                document.querySelector('.preview-container').insertAdjacentHTML('beforeend',image);
                document.querySelector('.file-count').textContent='1/9';};
            }''')
            path=tmp_path/'test.jpg';path.write_text(svg,encoding='utf-8')
            q=Qualification(index_name='资质3',qualification_no='',qualification_name='',expiry=Expiry(permanent=False),evidence_url='proof',files=(path,))
            view._upload_qualification_in(QualificationType('推广审查',(q,)),1,0,lambda:page.locator('#business'))
            assert len(saves)==len(uploads)==page.evaluate('window.refreshes')==1
            assert len(view._saved_file_receipts[(1,0)])==1
            return
        receipts=[UploadReceipt(Path('test.jpg'),'hash','file-a')]
        with CardSaveObserver(page) as observer:
            scope=(observer,observer.checkpoint(),{'liceid':'2'})
            view._save_qualification_card(lambda:page.locator('#card'),lambda:page.locator('#business'),'proof',receipts,'资质3',save_scope=scope)
            if mode=='pending_write':
                # 模拟同一观察窗口的另一次写入仍在途，不能因本次已成功就刷新。
                from src.card_save import SaveEvent
                observer.events.append(SaveEvent(object(),{'liceid':'other'}))
            if mode in ('recover','zero_create_id','normal'):
                view._wait_for_card_save_settle(lambda:page.locator('#business'),0,'资质3',receipts=receipts,evidence='proof',save_scope=scope)
                assert page.locator('#card').count()==1
            else:
                with pytest.raises(PageFlowError):
                    view._wait_for_card_save_settle(lambda:page.locator('#business'),0,'资质3',receipts=receipts,evidence='proof',save_scope=scope)
            assert len(saves)==1
            assert page.evaluate('window.refreshes')==(1 if mode in ('recover','zero_create_id','wrong_refresh') else 0)
            assert len(reads)==(1 if mode in ('normal','pending_write') else 2 if mode in ('wrong_read','no_callback') else 3)
    finally:page.close()
