from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError
from src.new_audit_qualification import NewAuditQualificationPage
from src.upload_identity import UploadReceipt


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        yield browser
        browser.close()


@pytest.fixture
def saved_card(browser):
    page = browser.new_page()
    requests = []

    def serve(route):
        if route.request.url.endswith('/submitlice'):
            requests.append(route.request)
            route.fulfill(json={'status': 0})
        elif '/preview?' in route.request.url:
            route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>')
        else:
            route.fulfill(body='test')

    page.route('**/*', serve)
    page.goto('https://fkzhunru.baidu.com/test')
    page.set_content('''
      <style>.el-loading-mask {width: 20px; height: 20px}</style>
      <main><section id="business">
        <div class="form-card" id="current">
          <input type="file"><span>举证链接</span><input id="evidence" value="https://example.test/proof">
          <span>资质状态</span><span id="status">已保存待送审</span>
          <div class="preview-container"><span class="file-count">1/9</span>
            <div class="preview-list-li"><img src="/preview?filename=file-a"></div>
          </div>
        </div>
        <div class="form-card" id="other"></div>
      </section></main>
      <script>
        const card = document.querySelector('#current');
        card.__vueParentComponent = {subTree: {el: card}, exposed: {handleSubmit: () =>
          fetch('/permit/web/permit/submitlice', {method:'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({upload_file:'file-a', evidence_url:document.querySelector('#evidence').value})})
        }};
      </script>
    ''')
    receipts = [UploadReceipt(Path('test.jpg'), 'hash', 'file-a')]
    view = NewAuditQualificationPage(page, timeout=2200)
    yield page, view, receipts, requests
    page.close()


def test_other_card_loading_does_not_block_saved_card(saved_card):
    page, view, _, _ = saved_card
    page.locator('#other').evaluate("e => e.innerHTML = '<div class=el-loading-mask></div>'")
    # Also protects the compatibility path without file receipts.
    view._wait_for_card_save_settle(lambda: page.locator('#business'), 0, '资质2')


@pytest.mark.parametrize('mode', ['normal', 'stale_status', 'other_loading', 'rebuild', 'delayed_data', 'hidden_loading', 'empty_evidence'])
def test_successful_save_waits_for_matching_card_data(saved_card, mode, caplog):
    page, view, receipts, requests = saved_card
    caplog.set_level('INFO')
    evidence = '' if mode == 'empty_evidence' else 'https://example.test/proof'
    view._save_qualification_card(lambda: page.locator('#current'),
                                 lambda: page.locator('#business'), evidence, receipts, '资质2')
    page.evaluate('''mode => {
      if (mode === 'stale_status') document.querySelector('#status').textContent = '待保存';
      if (mode === 'other_loading') document.querySelector('#other').innerHTML = '<div class=el-loading-mask></div>';
      if (mode === 'hidden_loading') document.querySelector('#current').insertAdjacentHTML('beforeend', '<div class=el-loading-mask style="display:none"></div>');
      if (mode === 'rebuild') {
        const card = document.querySelector('#current');
        const copy = card.cloneNode(true); card.remove();
        setTimeout(() => document.querySelector('#business').prepend(copy), 350);
      }
      if (mode === 'delayed_data') {
        const input = document.querySelector('#evidence'); input.value = '';
        setTimeout(() => input.value = 'https://example.test/proof', 350);
      }
    }''', mode)
    view._wait_for_card_save_settle(lambda: page.locator('#business'), 0, '资质2',
                                   receipts=receipts, evidence=evidence)
    assert len(requests) == 1
    assert '保存接口成功' in caplog.text
    assert page.locator('#current').count() == 1
    assert page.locator('#evidence').input_value() == evidence


@pytest.mark.parametrize(('mode', 'message'), [
    ('card_loading', '加载遮罩'), ('parent_loading', '加载遮罩'),
    ('body_loading', '加载遮罩'), ('missing_card', '卡片未出现'),
    ('missing_file', '文件身份'), ('wrong_file', '文件身份'),
    ('wrong_evidence', '举证链接'), ('unloaded_image', '图片未加载'),
])
def test_incomplete_card_never_passes_with_successful_receipt(saved_card, mode, message):
    page, view, receipts, requests = saved_card
    view._save_qualification_card(lambda: page.locator('#current'),
                                 lambda: page.locator('#business'),
                                 'https://example.test/proof', receipts, '资质2')
    view.timeout = 1500
    page.evaluate('''mode => {
      const card = document.querySelector('#current');
      const addMask = element => element.insertAdjacentHTML('beforeend', '<div class=el-loading-mask></div>');
      if (mode === 'card_loading') addMask(card);
      if (mode === 'parent_loading') addMask(document.querySelector('main'));
      if (mode === 'body_loading') addMask(document.body);
      if (mode === 'missing_card') card.remove();
      if (mode === 'missing_file') card.querySelector('.preview-list-li').remove();
      if (mode === 'wrong_file') card.querySelector('img').src = '/preview?filename=other-file';
      if (mode === 'wrong_evidence') document.querySelector('#evidence').value = 'private-value';
      if (mode === 'unloaded_image') Object.defineProperty(card.querySelector('img'), 'naturalWidth', {value:0});
    }''', mode)
    with pytest.raises(PageFlowError, match=message) as error:
        view._wait_for_card_save_settle(lambda: page.locator('#business'), 0, '资质2',
                                       receipts=receipts, evidence='https://example.test/proof')
    assert 'private-value' not in str(error.value)
    assert len(requests) == 1


def test_status_is_required_without_file_receipts(saved_card):
    page, view, _, _ = saved_card
    view.timeout = 1500
    page.locator('#status').evaluate("e => e.textContent = '待保存'")
    with pytest.raises(PageFlowError, match='无文件身份凭据'):
        view._wait_for_card_save_settle(lambda: page.locator('#business'), 0, '资质2')


def test_late_reset_restarts_stability_wait(saved_card):
    page, view, receipts, _ = saved_card
    view.timeout = 3500
    page.evaluate('''() => {
      window.restoredAt = null;
      setTimeout(() => {
        document.querySelector('#evidence').value = '';
        setTimeout(() => {
          document.querySelector('#evidence').value = 'https://example.test/proof';
          window.restoredAt = performance.now();
        }, 400);
      }, 650);
    }''')
    view._wait_for_card_save_settle(lambda: page.locator('#business'), 0, '资质2',
                                   receipts=receipts, evidence='https://example.test/proof')
    assert page.evaluate('window.restoredAt !== null && performance.now() - window.restoredAt >= 1000')
