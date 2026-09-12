import time

import pytest
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError
from src.new_audit_qualification import NewAuditQualificationPage


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize('mode', ['slow', 'delayed', 'never', 'error', 'fill', 'throw'])
def test_active_autosave(browser, mode, monkeypatch):
    page = browser.new_page()
    page.route('https://fkzhunru.baidu.com/test', lambda route: route.fulfill(body='test'))
    page.goto('https://fkzhunru.baidu.com/test')
    requests = []
    def save(route):
        requests.append(route.request)
        route.fulfill(json={'status': 1 if mode == 'error' else 0})
    page.route('**/permit/web/permit/submitlice', save)
    page.set_content('''<section style="width:900px;height:500px">
        <div class="form-card" style="width:450px;height:250px">
        <input type="file"><input id="evidence"></div></section>
        <script>
        window.leaves=0; window.started=false;
        window.mode=MODE;
        const card=document.querySelector('.form-card');
        async function save(){
          if(window.started)return;
          window.started=true;
          const response=await fetch('/permit/web/permit/submitlice',{method:'POST'});
          await response.json();
        }
        window.methodCalls=0;
        card.onmouseleave=()=>{window.leaves++;};
        card.__vueParentComponent={subTree:{el:card},exposed:{handleSubmit:()=>{
          window.methodCalls++;
          if(mode==='never')return;
          if(mode==='throw')return Promise.reject(new Error('test'));
          return save();
        }}};
        document.querySelector('#evidence').oninput=()=>{if(mode==='fill')save();};
        </script>'''.replace('MODE', repr(mode)))
    # 延迟服务器响应，但请求已被监听；绝不能再次移入移出触发保存。
    if mode in ('slow', 'delayed'):
        page.unroute('**/permit/web/permit/submitlice')
        page.route('**/permit/web/permit/submitlice', lambda route: requests.append(route))
    if mode == 'delayed':
        wait = page.wait_for_timeout
        first_seen = None
        fulfilled = False
        def delayed_wait(ms):
            nonlocal first_seen, fulfilled
            wait(ms)
            if requests and first_seen is None:
                first_seen = time.monotonic()
            if first_seen is not None and not fulfilled and time.monotonic() - first_seen > 1.5:
                requests[0].fulfill(json={'status': 0})
                fulfilled = True
        monkeypatch.setattr(page, 'wait_for_timeout', delayed_wait)
    view = NewAuditQualificationPage(page, timeout=3500)
    card = lambda: page.locator('.form-card')
    try:
        if mode in ('never', 'error', 'slow', 'throw'):
            message = {'never': '未发出保存请求', 'error': '自动保存失败', 'slow': '已发出保存请求', 'throw': '页面保存方法执行失败'}[mode]
            with pytest.raises(PageFlowError, match=message):
                view._save_qualification_card(card, lambda: page.locator('section'), 'proof', [], '资质2')
        else:
            view._save_qualification_card(card, lambda: page.locator('section'), 'proof', [], '资质2')
        assert len(requests) == (0 if mode in ('never', 'throw') else 1)
        assert page.evaluate('window.methodCalls') == (0 if mode == 'fill' else 1)
        assert page.evaluate('window.leaves') == 0
    finally:
        page.close()


def test_scroll_both_document_and_inner_container(browser):
    page = browser.new_page()
    page.set_content('''<div style="height:1500px"></div>
      <section style="height:200px;overflow:auto"><div style="height:800px"></div>
      <div id="card" style="height:100px">card</div></section>''')
    view = NewAuditQualificationPage(page, timeout=3000)
    view._scroll_upload_to_bottom(page.locator('#card'))
    assert page.evaluate('document.scrollingElement.scrollTop + innerHeight >= document.scrollingElement.scrollHeight - 1')
    assert page.locator('section').evaluate('e=>e.scrollTop+e.clientHeight >= e.scrollHeight-1')
    page.close()


def test_tall_card_uses_visible_outside_point(browser):
    page = browser.new_page()
    page.set_content('''<section style="width:900px;height:1800px">
      <div id="card" style="width:450px;height:1700px">卡片</div></section>
      <script>window.left=false;document.querySelector('#card').onmouseleave=()=>window.left=true;</script>''')
    view = NewAuditQualificationPage(page, timeout=5000)
    view._scroll_upload_to_bottom(page.locator('#card'))
    view._click_blank_outside_card(page.locator('#card'), page.locator('section'))
    assert page.evaluate('window.left')
    page.close()


@pytest.mark.parametrize('kind', ['missing', 'wrong_root', 'ambiguous'])
def test_save_method_must_belong_to_current_card(browser, kind):
    page = browser.new_page()
    page.set_content('<section><div id="card">card</div></section>')
    page.evaluate("""kind=>{
      window.called=0;const card=document.querySelector('#card');
      const component={subTree:{el:kind==='wrong_root'?document.body:card},
        exposed:kind==='missing'?{}:{handleSubmit:()=>window.called++}};
      if(kind==='ambiguous')component.parent={subTree:{el:card},exposed:{handleSubmit:()=>window.called++}};
      card.__vueParentComponent=component;
    }""", kind)
    with pytest.raises(PageFlowError, match='唯一的页面保存方法'):
        NewAuditQualificationPage(page)._invoke_card_save(page.locator('#card'))
    assert page.evaluate('window.called') == 0
    page.close()


def test_production_vnode_tree_resolves_only_current_wrapped_card(browser):
    page = browser.new_page()
    page.set_content('<main><div class="drag-upload-wrapper"><div class="form-card" id="first"></div></div><div class="drag-upload-wrapper"><div class="form-card" id="second"></div></div></main>')
    page.evaluate("""()=>{
      window.calls=[];
      const components=[...document.querySelectorAll('.drag-upload-wrapper')].map((root,i)=>({
        component:{subTree:{el:root},exposed:{handleSubmit:()=>window.calls.push(i)}}
      }));
      document.querySelector('main')._vnode={component:{subTree:{children:components}}};
    }""")
    handle=NewAuditQualificationPage(page)._invoke_card_save(page.locator('#second'))
    assert page.evaluate('window.calls') == [1]
    handle.dispose()
    # 保存回调重新渲染当前卡片后，必须解析新的组件实例。
    page.evaluate("""()=>{
      const old=document.querySelector('#second').parentElement;
      const root=document.createElement('div');root.className='drag-upload-wrapper';
      root.innerHTML='<div class="form-card" id="second"></div>';old.replaceWith(root);
      document.querySelector('main')._vnode.component.subTree.children[1]={component:{
        subTree:{el:root},exposed:{handleSubmit:()=>window.calls.push(2)}
      }};
    }""")
    handle=NewAuditQualificationPage(page)._invoke_card_save(page.locator('#second'))
    assert page.evaluate('window.calls') == [1, 2]
    handle.dispose()
    page.close()
