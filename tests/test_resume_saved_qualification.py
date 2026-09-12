"""已保存推广审查续传：本地页面、真实文件内容核验。"""
from pathlib import Path
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError
from src.models import Qualification, QualificationType, Expiry
from src.new_audit_qualification import NewAuditQualificationPage


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b=p.chromium.launch(channel='chrome',headless=True)
        yield b
        b.close()


@pytest.mark.parametrize('mode',['complete','partial','wrong_content','wrong_order','extra','unsaved','evidence','new_nonempty'])
def test_resume_requires_verified_saved_prefix(browser,tmp_path,mode):
    images={f'file-{i}':f'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="{color}"/></svg>'
            for i,color in enumerate(['red','blue','green','black'],1)}
    files=[]
    for i in range(1,4):
        p=tmp_path/f'{i}.jpg';p.write_text(images[f'file-{i}']);files.append(p)
    ids=['file-1','file-2'] if mode=='partial' else ['file-1','file-2','file-3']
    if mode=='wrong_order':ids=['file-2','file-1','file-3']
    if mode=='extra':ids.append('file-4')
    page=browser.new_page();uploads=[];saves=[]
    def serve(route):
        url=route.request.url
        if url.endswith('/savelicepic'):
            uploads.append(1);route.fulfill(json={'status':0,'data':'file-3'})
        elif url.endswith('/submitlice'):
            saves.append(route.request.post_data_json);route.fulfill(json={'status':0})
        elif '/getlicepic?' in url:
            key=parse_qs(urlsplit(url).query)['filename'][0]
            route.fulfill(content_type='image/svg+xml',body=images['file-4' if mode=='wrong_content' else key])
        else:route.fulfill(body='test')
    page.route('**/*',serve);page.goto('https://fkzhunru.baidu.com/test')
    page.set_content('''<section><div class=form-card style="width:500px;height:200px">
      <input type=file><input id=evidence value="proof"><span id=status>已保存待送审</span>
      <div class=preview-container><span class=file-count></span><div id=files></div></div>
      </div></section><script>
      window.ids=IDS;window.calls=0;
      function render(){document.querySelector('#files').innerHTML=ids.map(id=>'<div class=preview-list-li><img src="/permit/web/permit/getlicepic?filename='+id+'"></div>').join('');
        document.querySelector('.file-count').textContent=ids.length+'/9';}
      const card=document.querySelector('.form-card');
      card.__vueParentComponent={subTree:{el:card},exposed:{handleSubmit:()=>{
        window.calls++;return fetch('/permit/web/permit/submitlice',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({upload_file:ids.join(','),evidence_url:document.querySelector('#evidence').value})});}}};
      card.querySelector('input[type=file]').onchange=async()=>{
        const r=await fetch('/permit/web/permit/savelicepic',{method:'POST'});const body=await r.json();ids.push(body.data);render();};
      render();
      </script>'''.replace('IDS',json.dumps(ids)))
    if mode=='unsaved':page.locator('#status').evaluate("e=>e.textContent='待保存'")
    if mode=='evidence':page.locator('#evidence').fill('old-proof')
    q=Qualification(index_name='资质1',qualification_no='',qualification_name='',expiry=Expiry(permanent=False),evidence_url='proof',files=tuple(files))
    view=NewAuditQualificationPage(page,timeout=3000)
    try:
        if mode in ('complete','partial','evidence'):
            view._upload_type_in(QualificationType('推广审查',(q,)),0,lambda:page.locator('section'),resume_existing=True)
            assert len(view._saved_file_receipts[(0,0)])==3
            assert len(uploads)==(1 if mode=='partial' else 0)
            assert len(saves)==(0 if mode=='complete' else 1)
            if saves:assert saves[-1]=={'upload_file':'file-1,file-2,file-3','evidence_url':'proof'}
        else:
            with pytest.raises(PageFlowError):
                view._upload_type_in(QualificationType('推广审查',(q,)),0,lambda:page.locator('section'),resume_existing=mode!='new_nonempty')
            assert uploads==saves==[]
    finally:page.close()
