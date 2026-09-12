"""空业务新增默认组：真实 DOM 切换、选择、删除及编号重排。"""
import json
import pytest
from playwright.sync_api import sync_playwright
from src.errors import PageFlowError
from src.models import QualificationType
from src.new_audit_qualification import NewAuditQualificationPage

@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        yield browser
        browser.close()

@pytest.mark.parametrize('mode', ['exact','select','nonempty','saved','missing_form','existing','duplicate','fixed'])
def test_default_group_from_empty(browser,mode):
    page=browser.new_page()
    page.set_content('''<button id=add>新增业务资质</button><nav></nav><main></main><aside></aside><script>
    let mode=MODE, active=0, adds=0;
    let cards=mode==='existing'?[{name:'原业务'}]:[];
    window.deleted=0;
    function render(){
      document.querySelector('nav').innerHTML=cards.map((c,i)=>`<button onclick="active=${i};render()">业务${i+1}</button>`).join('');
      document.querySelector('main').innerHTML=cards.map((c,i)=>`<section class="business-form-card" style="display:${i===active?'block':'none'}">
        <h2>业务${i+1}</h2><button onclick="cards.splice(${i},1);window.deleted++;active=0;render()">删除</button>
        <label>经营业务<input role=combobox ${mode==='fixed'&&i<3?'readonly':''} placeholder="经营类目" value="${c.name}" oninput="options(this,${i})"></label>
        ${mode==='missing_form'?'':`<div class=form-card><input type=file><input value="${mode==='nonempty'?'已有举证':''}"><span>${mode==='saved'?'已保存待送审':''}</span><span class=file-count>0/9</span></div>`}
        </section>`).join('');
    }
    function options(input,index){document.querySelector('aside').innerHTML='<div role=option>一类医疗器械（不可个人，B）</div>';document.querySelector('[role=option]').onclick=()=>{cards[index].name='一类医疗器械（不可个人，B）';document.querySelector('aside').innerHTML='';render();};}
    document.querySelector('#add').onclick=()=>{if(mode==='fixed'&&adds++){cards.push({name:''});render();return;}cards.push({name:'推广审查'},{name:(mode==='select'||mode==='fixed')?'其它':'一类医疗器械（不可个人，B）'},{name:mode==='duplicate'?'一类医疗器械（不可个人，B）':'其它'});render();};render();
    </script>'''.replace('MODE',json.dumps(mode)))
    view=NewAuditQualificationPage(page,timeout=3000)
    try:
        if mode in ('exact','select','fixed'):
            assert view.add_business(QualificationType('一类医疗器械',()))==1
            assert page.evaluate('window.deleted')==(3 if mode=='fixed' else 2)
            assert view._business_indices_matching('一类医疗器械')==[1]
        else:
            with pytest.raises(PageFlowError):view.add_business(QualificationType('一类医疗器械',()))
            assert page.evaluate('window.deleted')==0
    finally:page.close()
