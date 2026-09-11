import json
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import sync_playwright

from src.errors import AuthenticationRequired, PageFlowError
from src.url_overview import _matches_query, _query_and_wait, _query_data
from src.workflow import select_url_and_open_industry_qualification, _find_url_row


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize('mode', ['success', 'initial_delayed', 'filters', 'status_filter',
                                 'empty', 'similar', 'duplicate', 'error', 'stale',
                                 'loading', 'many_pages', 'same_result', 'old_toast', 'stale_data',
                                 'http_error', 'invalid_json', 'bad_schema', 'network_error'])
def test_search_url_waits_for_current_exact_results(browser, mode):
    page = browser.new_page()
    page.route('**/*', lambda route: route.fulfill(body='test'))
    page.goto('https://fkzhunru.baidu.com/test')
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
    async function loadRows(){
      const params = new URLSearchParams({url: inputs[1].value, page_num:'1', page_size:'10'});
      const response = await fetch('/permit/web/permit/geturllist?' + params);
      const payload = await response.json();
      if(payload.status !== 0) throw new Error('query failed');
      return payload.data.list;
    }
    async function query(){
      window.queries.push(inputs[1].value);
      if(inputs[0].value||window.initializing||document.querySelector('.el-select__selected-item').textContent)window.wrong=true;
      if(MODE==='stale')return;
      const rows = await loadRows();
      if(MODE==='loading'){document.querySelector('.el-skeleton').hidden=false;return;}
      if(MODE!=='same_result')refresh(MODE==='stale_data' ? INITIAL : rows);
      if(MODE==='many_pages')document.querySelector('.btn-next').disabled=false;
    }
    async function resetFilters(){window.resets++;inputs[0].value='';inputs[1].value='';
      document.querySelector('.el-select__selected-item').textContent='';refresh(await loadRows());}
    if(MODE==='filters')inputs[0].value='999';
    if(MODE==='status_filter')document.querySelector('.el-select__selected-item').textContent='审核中';
    if(MODE==='initial_delayed'){
      window.initializing=true;document.querySelector('.el-skeleton').hidden=false;
      setTimeout(()=>{render(INITIAL);document.querySelector('.el-skeleton').hidden=true;window.initializing=false;},300);
    }else render(INITIAL);
    </script>'''.replace('INITIAL', json.dumps(initial)).replace('RESULT', json.dumps(result)).replace('MODE', json.dumps(mode))
    def serve_query(route):
        if mode == 'network_error':
            route.abort('failed')
            return
        if mode == 'http_error':
            route.fulfill(status=503, body='unavailable')
            return
        if mode == 'invalid_json':
            route.fulfill(body='not json')
            return
        if mode == 'bad_schema':
            route.fulfill(json={'status': 0, 'data': None})
            return
        query = parse_qs(urlsplit(route.request.url).query, keep_blank_values=True)
        rows = result if query.get('url') == [target] else initial
        route.fulfill(json={'status': 1 if mode == 'error' else 0,
                            'data': {'count': len(rows), 'list': rows}})
    page.route('**/permit/web/permit/geturllist**', serve_query)
    page.set_content(html)
    if mode == 'old_toast':
        page.evaluate("document.body.insertAdjacentHTML('beforeend', '<div class=el-message--error>其他请求失败</div>')")
    # 只能监听页面点击发出的请求，不自行调用API或等待全页网络空闲。
    def unexpected(*args, **kwargs):
        pytest.fail('unexpected direct network operation')
    page.wait_for_load_state = unexpected
    if mode in ('success', 'initial_delayed', 'filters', 'status_filter', 'same_result', 'old_toast'):
        assert select_url_and_open_industry_qualification(page, target, 2000) is page
        assert page.evaluate('window.clicked') == 22
    else:
        with pytest.raises(PageFlowError):
            select_url_and_open_industry_qualification(page, target, 1200)
        assert page.evaluate('window.clicked') is None
    assert page.evaluate('window.wrong') is False
    assert page.evaluate('window.queries') == [target]
    assert page.evaluate('window.resets') == (1 if mode in ('filters', 'status_filter') else 0)
    assert page.locator('.url-overview').evaluate('r=>r.__urlSearchStableSince===undefined')
    page.close()


def test_exact_matching_ignores_hidden_and_longer_urls(browser):
    page = browser.new_page()
    page.set_content('''<table><tr hidden><td>https://example.test/a</td></tr>
    <tr><td>https://example.test/abc</td></tr></table>''')
    assert _find_url_row(page, 'https://example.test/a') == (None, 0)
    page.close()


@pytest.mark.parametrize('mode', ['slow', 'pending', 'old_response', 'wrong_url',
                                 'wrong_page', 'wrong_host', 'wrong_path', 'wrong_method'])
def test_query_response_is_tied_to_current_page_request(browser, monkeypatch, mode):
    page = browser.new_page()
    page.route('**/*', lambda route: route.fulfill(body='test'))
    page.goto('https://fkzhunru.baidu.com/test')
    target = 'https://example.test/a?x=1&y=2'
    page.set_content('''<section class="url-overview">
      <button onclick="if(window.send)fetch(window.queryUrl, {method:window.method})">查询</button>
      <table><tbody><tr><td>22</td><td><a href="#"></a></td></tr></tbody></table>
      </section>''')
    page.locator('a').evaluate('(a, url) => a.textContent=url', target)
    page.evaluate('''({target, mode}) => {
      const url = new URL('/permit/web/permit/geturllist', location.origin);
      url.search = new URLSearchParams({url:target, page_num:'1'});
      if(mode==='wrong_url') url.searchParams.set('url', target+'0');
      if(mode==='wrong_page') url.searchParams.set('page_num', '2');
      if(mode==='wrong_host') url.hostname = 'example.test';
      if(mode==='wrong_path') url.pathname += '/other';
      window.queryUrl = url.href;
      window.method = mode==='wrong_method' ? 'POST' : 'GET';
      window.send = mode!=='old_response';
    }''', {'target': target, 'mode': mode})
    pending = []
    page.route('**/geturllist**', lambda route: pending.append(route))
    if mode == 'old_response':
        page.evaluate('() => { fetch(window.queryUrl); }')
        page.wait_for_timeout(100)
        assert len(pending) == 1
    started = time.monotonic()
    original_wait = page.wait_for_timeout
    fulfilled = False

    def wait(ms):
        nonlocal fulfilled
        original_wait(ms)
        if pending and not fulfilled and mode != 'pending' and time.monotonic() - started > .35:
            pending[0].fulfill(json={'status': 0, 'data': {
                'count': 1, 'list': [{'url': target, 'urlid': 22}]}})
            fulfilled = True

    monkeypatch.setattr(page, 'wait_for_timeout', wait)
    registered, removed = [], []
    original_on, original_remove = page.on, page.remove_listener
    monkeypatch.setattr(page, 'on', lambda event, handler: (registered.append((event, handler)), original_on(event, handler)))
    monkeypatch.setattr(page, 'remove_listener', lambda event, handler: (removed.append((event, handler)), original_remove(event, handler)))
    try:
        if mode == 'slow':
            assert _query_and_wait(page, page.locator('section'), page.get_by_role('button'), 1000, target)['count'] == 1
            assert time.monotonic() - started >= .35
        else:
            reason = '请求已发出但未完整返回' if mode == 'pending' else '未检测到本轮匹配请求'
            with pytest.raises(PageFlowError, match=reason):
                _query_and_wait(page, page.locator('section'), page.get_by_role('button'), 800, target)
        assert len(pending) == 1
        assert registered == removed
    finally:
        page.close()


@pytest.mark.parametrize('suffix', ['&url=https%3A%2F%2Fexample.test', '&page_num=2'])
def test_duplicate_query_parameters_are_not_accepted(suffix):
    request = SimpleNamespace(method='GET', url='https://fkzhunru.baidu.com/permit/web/permit/geturllist?url=https%3A%2F%2Fexample.test&page_num=1'+suffix)
    assert not _matches_query(request, 'https://example.test')


@pytest.mark.parametrize('payload', [[], {'status': False}, {'status': '0'},
                                    {'status': 0, 'data': {'count': -1, 'list': []}},
                                    {'status': 0, 'data': {'count': 1, 'list': [{}]}}])
def test_query_rejects_malformed_payload(payload):
    response = Mock(status=200)
    response.json.return_value = payload
    with pytest.raises(PageFlowError, match='结构异常'):
        _query_data(response)


def test_query_business_error_does_not_log_response_secrets():
    response = Mock(status=200)
    response.json.return_value = {'status': 3, 'message': 'token=secret-test-placeholder'}
    with pytest.raises(PageFlowError, match='status=3') as error:
        _query_data(response)
    assert 'secret-test-placeholder' not in str(error.value)


@pytest.mark.parametrize('status', [401, 403])
def test_query_unauthorized_requires_login(status):
    with pytest.raises(AuthenticationRequired, match='重新登录'):
        _query_data(Mock(status=status))
