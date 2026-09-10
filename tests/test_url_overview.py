import json

import pytest
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError
from src.workflow import select_url_and_open_industry_qualification, _find_url_row


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize('mode', ['success', 'initial_delayed', 'filters', 'status_filter',
                                 'empty', 'similar', 'duplicate', 'error', 'stale',
                                 'loading', 'many_pages', 'same_result'])
def test_search_url_waits_for_current_exact_results(browser, mode):
    page = browser.new_page()
    target = 'https://example.test/company?a=1&b=2'
    result = [{'urlid': 22, 'url': target}]
    if mode == 'empty': result = []
    if mode == 'similar': result = [{'urlid': 23, 'url': target + '0'}]
    if mode == 'duplicate': result.append({'urlid': 24, 'url': target})
    initial = [{'urlid': 22 if mode == 'same_result' else 11, 'url': target}]
    html = '''<button onclick="window.wrong=true">查询</button>
    <div class="url-overview"><h3>URL状态概览</h3><form onsubmit="return false">
    <input placeholder="请输入要查询的urlid">
    <input placeholder="请输入要查询的url链接">
    <div class="el-form-item">审核状态<span class="el-select__selected-item"></span></div>
    <button type="button" onclick="resetFilters()">重置</button>
    <button type="button" onclick="query()">查询</button></form>
    <div class="el-skeleton" hidden>加载</div><table><tbody></tbody></table>
    <div class="el-table__empty-block" hidden>暂无数据</div>
    <div class="el-pagination"><button class="btn-next" disabled onclick="window.wrong=true">下一页</button></div></div>
    <script>
    window.wrong=false; window.clicked=null; window.queries=[];window.resets=0;
    const inputs=document.querySelectorAll('input');
    function render(rows){document.querySelector('tbody').innerHTML=rows.map(r=>
      `<tr><td>${r.urlid}</td><td><a href="${r.url}">${r.url.replaceAll('&','&amp;')}</a></td>
      <td><button onclick="window.clicked=${r.urlid};document.body.insertAdjacentHTML('beforeend','<h2>行业资质</h2>')">查看</button></td></tr>`).join('');
      document.querySelector('.el-table__empty-block').hidden=rows.length>0;}
    function refresh(rows){
      document.querySelector('.el-skeleton').hidden=false;
      setTimeout(()=>{render(rows);document.querySelector('.el-skeleton').hidden=true;},200);
    }
    function query(){
      window.queries.push(inputs[1].value);
      if(inputs[0].value||window.initializing||document.querySelector('.el-select__selected-item').textContent)window.wrong=true;
      if(MODE==='stale')return;
      if(MODE==='error'){document.body.insertAdjacentHTML('beforeend','<div class="el-message--error">查询失败</div>');return;}
      if(MODE==='loading'){document.querySelector('.el-skeleton').hidden=false;return;}
      refresh(RESULT);
      if(MODE==='many_pages')document.querySelector('.btn-next').disabled=false;
    }
    function resetFilters(){window.resets++;inputs[0].value='';inputs[1].value='';
      document.querySelector('.el-select__selected-item').textContent='';refresh(INITIAL);}
    if(MODE==='filters')inputs[0].value='999';
    if(MODE==='status_filter')document.querySelector('.el-select__selected-item').textContent='审核中';
    if(MODE==='initial_delayed'){
      window.initializing=true;document.querySelector('.el-skeleton').hidden=false;
      setTimeout(()=>{render(INITIAL);document.querySelector('.el-skeleton').hidden=true;window.initializing=false;},300);
    }else render(INITIAL);
    </script>'''.replace('INITIAL', json.dumps(initial)).replace('RESULT', json.dumps(result)).replace('MODE', json.dumps(mode))
    page.set_content(html)
    # 查询实现不得依赖网络响应、网络空闲或自行调用接口。
    def unexpected(*args, **kwargs):
        pytest.fail('unexpected network operation')
    page.expect_response = unexpected
    page.wait_for_load_state = unexpected
    page.on = unexpected
    if mode in ('success', 'initial_delayed', 'filters', 'status_filter', 'same_result'):
        assert select_url_and_open_industry_qualification(page, target, 2000) is page
        assert page.evaluate('window.clicked') == 22
    else:
        with pytest.raises(PageFlowError):
            select_url_and_open_industry_qualification(page, target, 1200)
        assert page.evaluate('window.clicked') is None
    assert page.evaluate('window.wrong') is False
    assert page.evaluate('window.queries') == [target]
    assert page.evaluate('window.resets') == (1 if mode in ('filters', 'status_filter') else 0)
    assert page.locator('.url-overview').evaluate('r=>r.__urlSearchObservation===undefined')
    page.close()


def test_exact_matching_ignores_hidden_and_longer_urls(browser):
    page = browser.new_page()
    page.set_content('''<table><tr hidden><td>https://example.test/a</td></tr>
    <tr><td>https://example.test/abc</td></tr></table>''')
    assert _find_url_row(page, 'https://example.test/a') == (None, 0)
    page.close()
