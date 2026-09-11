import pytest
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError
from src.new_audit_qualification import NewAuditQualificationPage


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        instance = p.chromium.launch(channel='chrome', headless=True)
        yield instance
        instance.close()


@pytest.mark.parametrize('change', ['remove_heading', 'insert_heading', 'hide_tab', 'remove_target'])
def test_business_switch_keeps_exact_identity_after_scan(browser, monkeypatch, change):
    page = browser.new_page()
    page.set_content('''<button onclick="window.selected=1">业务1</button>
        <h2 id="heading">业务1</h2>
        <button id="target" onclick="window.selected=2">业务2</button>
        <div id="panel"></div><script>window.selected=null;</script>''')
    view = NewAuditQualificationPage(page, timeout=400)
    scan = view._business_tabs
    def changed_scan():
        tabs = scan()
        if change == 'remove_heading':
            page.locator('#heading').evaluate('e=>e.remove()')
        elif change == 'insert_heading':
            page.locator('#target').evaluate("e=>e.insertAdjacentHTML('beforebegin','<h2>业务1</h2>')")
        elif change == 'hide_tab':
            page.locator('#target').evaluate('''e=>{e.hidden=true;
                e.insertAdjacentHTML('afterend','<button onclick="window.selected=2">业务2</button>');}''')
        else:
            page.locator('#target').evaluate("e=>{e.textContent='业务3';e.onclick=()=>window.selected=3;}")
        return tabs
    monkeypatch.setattr(view, '_business_tabs', changed_scan)
    monkeypatch.setattr(view, '_business_container', lambda index:
                        page.locator('#panel') if page.evaluate('window.selected') == index else None)
    if change == 'remove_target':
        with pytest.raises(PageFlowError, match="业务2标签"):
            view._click_business_tab(2)
        assert page.evaluate('window.selected') is None
    else:
        view._click_business_tab(2)
        assert page.evaluate('window.selected') == 2
    page.close()
