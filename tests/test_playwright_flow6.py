from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError
from src.industry_qualification import IndustryQualificationPage
from src.models import Expiry, Qualification, QualificationType
from src.new_audit_qualification import NewAuditQualificationPage
from src.qualification_form import QualificationForm
from src.workflow import (
    WorkflowConfig,
    WorkflowRunner,
    enter_qualification_page,
    select_url_and_open_industry_qualification,
    submit_all_qualifications,
)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel="chrome", headless=True)
        yield instance
        instance.close()


def test_pending_review_url_opens_industry_qualification(browser) -> None:
    target_url = "https://qianhu.wejianzhan.com/2024-09-06heh2"
    page = browser.new_page()
    page.set_content(
        f"""
        <h2>URL状态概览</h2>
        <table>
          <tr>
            <th>URL ID</th><th>URL</th><th>信息资质状态</th><th>操作区</th>
          </tr>
          <tr>
            <td>57926626</td>
            <td><a href="{target_url}">{target_url}</a></td>
            <td>待审核</td>
            <td><button id="view">查看</button></td>
          </tr>
        </table>
        <script>
          window.viewClicked = false;
          document.querySelector('#view').addEventListener(
            'click',
            () => {{
              window.viewClicked = true;
              const heading = document.createElement('h2');
              heading.textContent = '行业资质';
              document.body.appendChild(heading);
            }}
          );
        </script>
        """
    )

    detail_page = select_url_and_open_industry_qualification(
        page,
        target_url,
        timeout=10_000,
    )

    assert detail_page is page
    assert page.evaluate("window.viewClicked") is True
    assert page.get_by_text("行业资质", exact=True).count() == 1
    page.close()


def test_new_url_row_view_opens_invest_qualification_in_new_page(browser) -> None:
    context = browser.new_context()
    target_url = "https://example.test/company"
    overview_url = "https://fkzhunru.baidu.com/newaudit#/lice/submit/10001/1/token/0"
    detail_url = (
        "https://fkzhunru.baidu.com/newaudit#/lice/"
        "invest_lice_list/10001/1/token/0/30003"
    )
    request_count = 0

    def serve(route) -> None:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body=f"""
                <h2>URL状态概览</h2>
                <table>
                  <tr><th>URL</th><th>操作区</th></tr>
                  <tr>
                    <td><a href="{target_url}">{target_url}</a></td>
                    <td><button onclick="window.open('{detail_url}', '_blank')">查看</button></td>
                  </tr>
                </table>
                """,
            )
        else:
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body="<h2>投放资质</h2><button>新增资质</button>",
            )

    context.route("https://fkzhunru.baidu.com/**", serve)
    overview_page = context.new_page()
    overview_page.goto(overview_url, wait_until="domcontentloaded")

    detail_page = select_url_and_open_industry_qualification(
        overview_page,
        target_url,
        timeout=2_000,
    )

    assert detail_page is not overview_page
    assert detail_page.url == detail_url
    assert detail_page.get_by_text("投放资质", exact=True).is_visible()
    context.close()


def test_new_audit_entry_opens_qualification_overview_in_new_page(browser) -> None:
    context = browser.new_context()
    landing_url = "https://fkzhunru.baidu.com/newaudit#/lice/10001/1/token"
    submit_url = "https://fkzhunru.baidu.com/newaudit#/lice/submit/10001/1/token/0"
    request_count = 0

    def serve(route) -> None:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body=f"""
                <section id="qualification-card">
                  <h2>资质信息审核</h2>
                  <button id="qualification-view" onclick="window.open('{submit_url}', '_blank')">查看</button>
                </section>
                <section id="auth-card">
                  <h2>真实性认证</h2>
                  <button id="auth-view" onclick="window.authClicked = true">查看</button>
                </section>
                """,
            )
        else:
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body="<h2>URL状态概览</h2>",
            )

    context.route("https://fkzhunru.baidu.com/**", serve)
    page = context.new_page()

    overview_page, final_url = enter_qualification_page(page, landing_url, 2_000)

    assert final_url == submit_url
    assert overview_page.get_by_text("URL状态概览", exact=True).is_visible()
    assert page.evaluate("window.authClicked") is None
    context.close()


@pytest.mark.parametrize("lose_files_on_save", [False, True])
def test_new_audit_business_cleanup_and_one_qualification_per_form(
    browser,
    tmp_path: Path,
    lose_files_on_save,
) -> None:
    context = browser.new_context()
    page_url = "https://fkzhunru.baidu.com/newaudit#/lice/add_invest_lice/10001/token"
    html = """
    <div id="tabs">
      <span class="business-tab" data-index="1"><button>业务1</button></span>
      <span class="business-tab" data-index="2"><button>业务2</button><button aria-label="关闭业务2">×</button></span>
      <span class="business-tab" data-index="3"><button>业务3</button><button aria-label="关闭业务3">×</button></span>
      <span class="business-tab" data-index="4"><button>业务4</button><button aria-label="关闭业务4">×</button></span>
    </div>
    <section id="business-1" class="business-card" data-index="1">
      <h2>业务1</h2>
      <div class="business-field"><span>*</span><span>经营业务</span><span>推广审查</span></div>
      <div id="forms">
        <div class="file-form form-card" style="width:60%">
          <span>资质图片</span><input type="file" multiple>
          <div class="preview-container"><span class="file-count" style="display:none"></span></div>
          <span>资质状态</span><span class="save-status">待保存</span>
          <span>举证链接</span><input placeholder="请输入">
        </div>
      </div>
      <label><input id="supplement" type="checkbox">我还需要补充其他资质</label>
      <button id="more">新增补充资质</button>
    </section>
    <section class="business-card" data-index="2"><h2>业务2</h2><div class="business-field"><span>经营业务</span><span>三类医疗器械（不可个人，B）</span></div><input type="file" multiple><span>举证链接</span><input><span>我还需要补充其他资质</span></section>
    <section class="business-card" data-index="3"><h2>业务3</h2><div class="business-field"><span>经营业务</span><span>入驻商城类（不可个人，C2）</span></div><input type="file" multiple><span>举证链接</span><input><span>我还需要补充其他资质</span></section>
    <section class="business-card" data-index="4"><h2>业务4</h2><div class="business-field"><span>经营业务</span><span>电商代运营【房产承诺函传营业执照（如未要求提交承诺函请忽略）】</span></div><input type="file" multiple><span>举证链接</span><input><span>我还需要补充其他资质</span></section>
    <script>
      document.querySelectorAll('[aria-label^="关闭业务"]').forEach(button => {
        button.addEventListener('click', () => {
          const index = button.parentElement.dataset.index;
          button.parentElement.remove();
          document.querySelector(`.business-card[data-index="${index}"]`).remove();
        });
      });
      function addForm() {
        const form = document.createElement('div');
        form.className = 'file-form form-card';
        form.style.width = '60%';
        form.innerHTML = '<span>资质图片</span><input type="file" multiple>' +
          '<div class="preview-container"><span class="file-count" style="display:none"></span></div>' +
          '<span>资质状态</span><span class="save-status">待保存</span>' +
          '<span>举证链接</span><input placeholder="请输入">';
        document.querySelector('#forms').appendChild(form);
        bind(form);
      }
      function bind(root) {
            root.querySelector('input[type="file"]').addEventListener(
              'change', async event => {
                window.batchSizes = [...(window.batchSizes || []), event.target.files.length];
                for (const file of event.target.files) {
                  const response = await fetch('/permit/web/permit/savelicepic', {method: 'POST'});
                  const result = await response.json();
                  root.dataset.ids = [root.dataset.ids, result.data].filter(Boolean).join(',');
                  const li = document.createElement('li');
                  li.className = 'preview-list-li';
                  li.innerHTML = '<img src="/permit/get?filename=' + result.data + '">';
                  root.querySelector('.preview-container').appendChild(li);
                }
                // 浏览器的 response 事件早于上传组件 success 回调及 Vue 状态回填。
                await new Promise(resolve => setTimeout(resolve, 350));
                const uploaded = Number(root.dataset.uploadedCount || 0) + event.target.files.length;
                root.dataset.uploadedCount = String(uploaded);
                const count = root.querySelector('.file-count');
                count.textContent = `${uploaded}/9`;
                count.style.display = 'inline';
                root.dataset.uploaded = 'true';
              }
            );
            root.addEventListener('mouseleave', () => {
              if (root.dataset.uploaded === 'true') {
                fetch('/permit/web/permit/submitlice', {method: 'POST', headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({upload_file:root.dataset.ids, evidence_url:root.querySelector('input[placeholder]').value})}).then(async () => {
                  await new Promise(resolve => setTimeout(resolve, 350));
                  root.querySelector('.save-status').textContent = '已保存待送审';
                  if (window.loseFilesOnSave) root.querySelector('.file-count').textContent = '0/9';
                });
              }
            });
      }
      bind(document.querySelector('.file-form'));
      document.querySelector('#supplement').addEventListener('change', addForm);
      document.querySelector('#more').addEventListener('click', addForm);
    </script>
    """

    def serve_page(route) -> None:
        route.fulfill(content_type="text/html; charset=utf-8", body=html)

    from io import BytesIO
    from PIL import Image
    png = BytesIO()
    Image.new('RGB', (2, 2), 'blue').save(png, format='PNG')
    image_bytes = png.getvalue()
    upload_calls = []
    def serve_upload(route):
        upload_calls.append(1)
        route.fulfill(status=200, content_type='application/json',
                      body=json.dumps({'status':0, 'data':f'{len(upload_calls)}.png'}))
    context.route('**/permit/get?filename=*', lambda route:route.fulfill(content_type='image/png', body=image_bytes))

    def serve_submitlice(route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": 0, "data": {}}',
        )

    context.route("https://fkzhunru.baidu.com/newaudit", serve_page)
    context.route("**/permit/web/permit/savelicepic", serve_upload)
    context.route("**/permit/web/permit/submitlice", serve_submitlice)
    page = context.new_page()
    page.goto(page_url, wait_until="domcontentloaded")
    files = []
    for index in range(3):
        path = tmp_path / f"file-{index}.jpg"
        path.write_bytes(image_bytes)
        files.append(path)
    qualification = Qualification(
        index_name="资质1",
        qualification_no="编号",
        qualification_name="名称",
        expiry=Expiry(permanent=True),
        evidence_url="https://example.test/evidence",
        files=tuple(files),
    )
    extra_files = []
    for index in range(2):
        path = tmp_path / f"extra-{index}.jpg"
        path.write_bytes(image_bytes)
        extra_files.append(path)
    second_qualification = Qualification(
        index_name="资质2",
        qualification_no="编号2",
        qualification_name="名称2",
        expiry=Expiry(permanent=True),
        evidence_url="https://example.test/evidence-2",
        files=tuple(extra_files),
    )
    qualification_type = QualificationType(
        "推广审查", (qualification, second_qualification)
    )
    new_page = NewAuditQualificationPage(page, timeout=2_000)

    page.evaluate("value => window.loseFilesOnSave = value", lose_files_on_save)
    new_page.remove_default_extra_businesses()
    if lose_files_on_save:
        with pytest.raises(PageFlowError, match="保存后页面文件不完整或未显示"):
            new_page.upload_type(qualification_type, 1)
        assert not new_page._saved_uploads
        assert page.evaluate("window.batchSizes") == [1, 1, 1]
        context.close()
        return
    new_page.upload_type(qualification_type, 1)
    new_page.validate_final_collection(((qualification_type, 1),))

    assert page.evaluate("window.batchSizes") == [1, 1, 1, 1, 1]
    assert sorted(new_page._business_tabs()) == [1]
    assert len(new_page._file_inputs(1)) == 2
    assert page.locator(".file-form").evaluate_all(
        "elements => elements.map(element => Number(element.dataset.uploadedCount))"
    ) == [3, 2]
    assert page.locator('.file-form input[placeholder="请输入"]').evaluate_all(
        "elements => elements.map(element => element.value)"
    ) == ["https://example.test/evidence", "https://example.test/evidence-2"]
    context.close()


def test_new_audit_real_business_card_excludes_other_cards(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <div class="item-tag"><span>业务1</span></div>
      <div class="item-tag"><span>业务2</span></div>
      <div class="business-form-card" id="existing">
        <div class="card-header"><span>业务1</span></div>
        <input type="file"><input role="combobox" placeholder="请选择日期" hidden>
      </div>
      <div class="business-form-card" id="blank">
        <div class="card-header"><span>业务2</span></div>
        <input class="el-select__input" role="combobox">
      </div>
    ''')
    view = NewAuditQualificationPage(page)
    card = view._business_container(2)
    assert card.get_attribute('id') == 'blank'
    assert view._business_query_inputs(card).count() == 1
    assert card.locator('input[type=file]').count() == 0
    page.close()


def test_new_audit_file_inputs_ignore_hidden_form_cards(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <section id="business">
        <div class="form-card"><span>资质图片</span><input type="file" style="display:none"></div>
        <div class="form-card" style="display:none"><input type="file"></div>
      </section>
    ''')

    inputs = NewAuditQualificationPage._file_inputs_in(page.locator('#business'))

    assert len(inputs) == 1
    assert inputs[0].get_attribute('style') == 'display:none'
    page.close()


def test_new_audit_discards_only_empty_initial_supplement(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <div><button>业务1</button></div>
      <section class="business-card">
        <h2>业务1</h2><div><span>经营业务</span><span>推广审查</span></div>
        <div class="form-card"><input type="file"><span>举证链接</span><input></div>
        <div class="add-reserve"><div id="extra" class="form-card"><input type="file"><span>举证链接</span><input></div></div>
        <label><input id="supplement" type="checkbox" checked>我还需要补充其他资质</label>
      </section>
      <script>
        document.querySelector('#supplement').addEventListener('change', () => {
          document.querySelector('#extra').closest('.add-reserve').remove();
        });
      </script>
    ''')
    view = NewAuditQualificationPage(page, timeout=2_000)

    view._discard_empty_initial_supplements(lambda: view._business_container(1))

    assert len(view._file_inputs(1)) == 1
    page.close()


def test_new_audit_refuses_to_discard_nonempty_initial_supplement(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <div><button>业务1</button></div>
      <section class="business-card">
        <h2>业务1</h2><div><span>经营业务</span><span>推广审查</span></div>
        <div class="form-card"><input type="file"><span>举证链接</span><input></div>
        <div class="add-reserve"><div class="form-card"><input type="file"><span class="file-count">1/9</span>
          <span>举证链接</span><input></div></div>
        <label><input type="checkbox" checked>我还需要补充其他资质</label>
      </section>
    ''')
    view = NewAuditQualificationPage(page, timeout=2_000)

    with pytest.raises(PageFlowError, match="非空补充资质草稿"):
        view._discard_empty_initial_supplements(lambda: view._business_container(1))

    assert len(view._file_inputs(1)) == 2
    page.close()


def test_new_audit_restores_unchecked_supplement_mode_before_adding(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <section id="business">
        <div class="add-reserve"><div class="form-card"><input type="file"></div></div>
        <div class="form-card"><input type="file"></div>
        <label><input id="supplement" type="checkbox">我还需要补充其他资质</label>
        <button id="more" style="display:none">新增补充资质</button>
      </section>
      <script>
        const checkbox = document.querySelector('#supplement');
        const button = document.querySelector('#more');
        checkbox.addEventListener('change', () => {
          button.style.display = checkbox.checked ? '' : 'none';
        });
        button.addEventListener('click', () => {
          const card = document.createElement('div');
          card.className = 'form-card';
          card.innerHTML = '<input type="file">';
          const reserve = document.createElement('div');
          reserve.className = 'add-reserve';
          reserve.appendChild(card);
          document.querySelector('#business').insertBefore(reserve, button);
        });
      </script>
    ''')
    view = NewAuditQualificationPage(page, timeout=2_000)

    view._ensure_upload_form_count_in(
        lambda: page.locator('#business'),
        3,
    )

    assert page.locator('#supplement').is_checked()
    assert len(view._file_inputs_in(page.locator('#business'))) == 3
    page.close()


def test_new_audit_waits_for_async_main_form_before_supplements(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <section id="business">
        <label><input type="checkbox">我还需要补充其他资质</label>
        <button id="more" onclick="window.moreClicked = true">新增补充资质</button>
      </section>
      <script>
        setTimeout(() => {
          const card = document.createElement('div');
          card.className = 'form-card';
          card.innerHTML = '<input type="file">';
          document.querySelector('#business').prepend(card);
        }, 250);
      </script>
    ''')
    view = NewAuditQualificationPage(page, timeout=2_000)

    view._ensure_upload_form_count_in(
        lambda: page.locator('#business'),
        1,
    )

    assert len(view._file_inputs_in(page.locator('#business'))) == 1
    assert page.evaluate('Boolean(window.moreClicked)') is False
    assert page.locator('input[type="checkbox"]').is_checked() is False
    page.close()


def test_new_audit_accepts_multiple_builtin_main_forms(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <section id="business">
        <div class="form-card"><input type="file"></div>
        <div class="form-card"><input type="file"></div>
        <label><input type="checkbox">我还需要补充其他资质</label>
      </section>
    ''')
    view = NewAuditQualificationPage(page, timeout=2_000)

    count = view._wait_for_initial_main_form_count(
        lambda: page.locator('#business')
    )
    view._ensure_upload_form_count_in(lambda: page.locator('#business'), 2)

    assert count == 2
    assert page.locator('input[type="checkbox"]').is_checked() is False
    page.close()


def test_new_audit_fills_two_builtin_forms_then_one_supplement(
    browser,
    tmp_path: Path,
) -> None:
    page = browser.new_page()
    page.route(
        '**/permit/web/permit/savelicepic',
        lambda route: route.fulfill(
            status=200, content_type='application/json', body='{"status":0}'
        ),
    )
    page.route(
        '**/permit/web/permit/submitlice',
        lambda route: route.fulfill(
            status=200, content_type='application/json', body='{"status":0}'
        ),
    )
    page.set_content('''
      <base href="https://fkzhunru.baidu.com/">
      <section id="business" style="width:1000px;min-height:500px">
        <div class="form-card" style="width:60%"><input type="file" multiple><span>举证链接</span><input></div>
        <div class="form-card" style="width:60%"><input type="file" multiple><span>举证链接</span><input></div>
        <label><input id="supplement" type="checkbox">我还需要补充其他资质</label>
        <button id="more">新增补充资质</button>
      </section>
      <script>
        function bind(card) {
          card.querySelector('input[type=file]').addEventListener('change', async event => {
            for (const file of event.target.files) {
              await fetch('/permit/web/permit/savelicepic', {method: 'POST'});
            }
          });
          card.addEventListener('mouseleave', () => {
            if (card.querySelector('input[type=file]').files.length) {
              fetch('/permit/web/permit/submitlice', {method: 'POST'});
            }
          });
        }
        document.querySelectorAll('.form-card').forEach(bind);
        document.querySelector('#supplement').addEventListener('change', () => {
          const reserve = document.createElement('div');
          reserve.className = 'add-reserve';
          reserve.innerHTML = '<div class="form-card" style="width:60%"><input type="file" multiple>' +
            '<span>举证链接</span><input></div>';
          document.querySelector('#business').insertBefore(
            reserve, document.querySelector('#more')
          );
          bind(reserve.querySelector('.form-card'));
        });
      </script>
    ''')
    qualifications = []
    for index in range(3):
        path = tmp_path / f'builtin-{index}.jpg'
        path.write_bytes(b'image')
        qualifications.append(Qualification(
            index_name=f'资质{index + 1}',
            qualification_no='',
            qualification_name='',
            expiry=Expiry(permanent=False),
            evidence_url=None,
            files=(path,),
        ))
    view = NewAuditQualificationPage(page, timeout=3_000)

    view._upload_type_in(
        QualificationType('电商代运营', tuple(qualifications)),
        1,
        lambda: page.locator('#business'),
    )

    assert len(view._file_inputs_in(page.locator('#business'))) == 3
    assert page.locator('.add-reserve').count() == 1
    assert page.locator('input[type=file]').evaluate_all(
        'inputs => inputs.map(input => input.files.length)'
    ) == [1, 1, 1]
    page.close()


def test_new_audit_rejects_disabled_exact_business_option(browser) -> None:
    page = browser.new_page()
    page.set_content('''
      <div class="business-form-card">
        <span>业务4</span><input role="combobox">
      </div>
      <ul role="listbox"><li role="option" aria-disabled="true"
        onclick="window.clicked = true">推广审查</li></ul>
    ''')
    with pytest.raises(PageFlowError, match='推广审查.*被百度禁用'):
        NewAuditQualificationPage(page, timeout=2_000)._select_business_type(4, '推广审查')
    assert not page.evaluate('Boolean(window.clicked)')
    page.close()


def test_new_audit_add_page_rejects_untrusted_origin(browser) -> None:
    page = browser.new_page()
    page.route('https://example.test/newaudit', lambda route: route.fulfill(
        body='<button>+ 新增业务资质</button>', content_type='text/html',
    ))
    page.goto('https://example.test/newaudit#/lice/create/test')
    assert not NewAuditQualificationPage(page)._is_new_audit_add_page()
    page.close()


def test_new_audit_waits_for_async_add_qualification_button(browser) -> None:
    context = browser.new_context()

    def serve(route) -> None:
        route.fulfill(
            content_type="text/html; charset=utf-8",
            body="""
            <h2>投放资质</h2>
            <div id="skeleton">加载中</div>
            <span id="add-page-title" style="display:none">新增投放资质</span>
            <button id="add-business" style="display:none">+ 新增业务资质</button>
            <script>
              setTimeout(() => {
                const add = document.createElement('button');
                add.textContent = '新增资质';
                add.addEventListener('click', () => {
                  location.hash = '/lice/create_invest_lice/10001/token';
                  document.querySelector('#add-page-title').style.display = 'block';
                  document.querySelector('#add-business').style.display = 'block';
                });
                document.body.appendChild(add);
                document.querySelector('#skeleton').remove();
              }, 150);
              document.querySelector('#add-business').addEventListener('click', () => {
                const tab = document.createElement('button');
                tab.textContent = '业务1';
                document.body.appendChild(tab);
              });
            </script>
            """,
        )

    context.route("https://fkzhunru.baidu.com/newaudit", serve)
    page = context.new_page()
    page.goto(
        "https://fkzhunru.baidu.com/newaudit#/lice/invest_lice_list/10001/token",
        wait_until="domcontentloaded",
    )

    NewAuditQualificationPage(page, timeout=2_000).enter_add_business_page()

    assert "/lice/create_invest_lice/" in page.url
    assert page.get_by_text("业务1", exact=True).is_visible()
    context.close()


def test_new_audit_resumes_saved_promotion_instead_of_adding(browser) -> None:
    context = browser.new_context()

    def serve(route) -> None:
        route.fulfill(
            content_type="text/html; charset=utf-8",
            body="""
            <button id="add">新增资质</button>
            <button>已备案业务资质</button>
            <table><tr><td>推广审查</td><td>已保存待送审</td>
              <td><button id="edit">修改</button></td></tr></table>
            <button id="add-business" style="display:none">+ 新增业务资质</button>
            <h2 id="edit-title" style="display:none">编辑投放资质</h2>
            <button id="cancel" style="display:none">取消</button>
            <div id="card" class="business-form-card" style="display:none">
              <span>业务1</span><div><span>经营业务</span><span>推广审查</span></div>
              <input type="file"><span>举证链接</span><input>
            </div>
            <script>
              document.querySelector('#add').onclick = () => { window.addClicked = true; };
              document.querySelector('#edit').onclick = () => {
                location.hash = '/lice/add_invest_lice/test';
                document.querySelector('#add-business').style.display = 'block';
                document.querySelector('#edit-title').style.display = 'block';
                document.querySelector('#cancel').style.display = 'block';
                document.querySelector('#card').style.display = 'block';
              };
            </script>
            """,
        )

    context.route("https://fkzhunru.baidu.com/newaudit", serve)
    page = context.new_page()
    page.goto("https://fkzhunru.baidu.com/newaudit#/lice/invest_lice_list/test")

    resumed = NewAuditQualificationPage(page, timeout=2_000).enter_add_business_page()

    assert page.evaluate("window.addClicked") is None
    assert resumed is True
    assert page.get_by_text("编辑投放资质", exact=True).is_visible()
    context.close()


def test_new_audit_final_collection_rejects_removed_upload_form(
    browser,
    tmp_path: Path,
) -> None:
    page = browser.new_page()
    page.route(
        "**/permit/web/permit/submitlice",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": 0}',
        ),
    )
    page.route(
        "**/permit/web/permit/savelicepic",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": 0, "data": "server-file.jpg"}',
        ),
    )
    page.set_content(
        """
        <base href="https://fkzhunru.baidu.com/">
        <div id="tabs"><button>业务1</button></div>
        <section class="business-card">
          <h2>业务1</h2>
          <div class="business-field"><span>经营业务</span><span>推广审查</span></div>
          <input placeholder="经营业务" value="推广审查">
          <div class="file-form form-card">
            <input type="file"><span>举证链接</span><input class="evidence">
          </div>
          <label><input type="checkbox">我还需要补充其他资质</label>
          <button>新增补充资质</button>
        </section>
        <script>
              document.querySelector('input[type="file"]').addEventListener(
                'change', async () => {
                  await fetch('/permit/web/permit/savelicepic', {method: 'POST'});
                }
              );
              document.querySelector('.file-form').addEventListener(
                'mouseleave', async () => {
                  await fetch('/permit/web/permit/submitlice', {method: 'POST'});
                }
              );
        </script>
        """
    )
    file_path = tmp_path / "promotion.jpg"
    file_path.write_bytes(b"image")
    qualification_type = QualificationType(
        "推广审查",
        (
            Qualification(
                index_name="资质1",
                qualification_no="",
                qualification_name="",
                expiry=Expiry(permanent=False),
                evidence_url=None,
                files=(file_path,),
            ),
        ),
    )
    new_page = NewAuditQualificationPage(page, timeout=2_000)
    new_page.upload_type(qualification_type, 1)
    page.locator(".file-form").evaluate("element => element.remove()")

    with pytest.raises(PageFlowError, match="表单数量不一致"):
        new_page.validate_final_collection(((qualification_type, 1),))

    page.close()


def test_new_audit_adds_business_and_selects_exact_mapped_option(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <div id="tabs"><span class="business-tab"><button>业务1</button></span></div>
        <button id="add">＋新增业务资质</button>
        <div id="editor"></div>
        <script>
          document.querySelector('#add').addEventListener('click', () => {
            const tab = document.createElement('span');
            tab.className = 'business-tab';
            tab.innerHTML = '<button>业务2</button>';
            document.querySelector('#tabs').appendChild(tab);
            document.querySelector('#editor').innerHTML = `<section class="business-card">
              <h2>业务2</h2>
              <label>经营业务
                <input placeholder="请选择符合该产品的经营类目">
              </label></section>`;
            const input = document.querySelector('#editor input');
            input.addEventListener('input', () => {
              setTimeout(() => {
                const listbox = document.createElement('div');
                listbox.setAttribute('role', 'listbox');
                listbox.innerHTML =
                  '<div role="option">入驻商城类（不可个人，C2）</div>' +
                  '<div role="option">三类医疗器械（不可个人，B）</div>';
                document.body.appendChild(listbox);
                listbox.querySelectorAll('[role="option"]').forEach(option => {
                  option.addEventListener('click', () => {
                    input.value = option.textContent;
                    listbox.remove();
                  });
                });
              }, 150);
            });
          });
        </script>
        """
    )
    qualification_type = QualificationType(
        "三类医疗器械",
        (
            Qualification(
                index_name="资质1",
                qualification_no="",
                qualification_name="",
                expiry=Expiry(permanent=False),
                evidence_url=None,
                files=(Path("/tmp/a.jpg"),),
            ),
        ),
    )
    new_page = NewAuditQualificationPage(page, timeout=2_000)

    index = new_page.add_business(qualification_type)

    assert index == 2
    assert page.locator("#editor input").input_value() == "三类医疗器械（不可个人，B）"
    page.close()


def test_new_audit_uploads_only_inside_requested_business(browser, tmp_path: Path) -> None:
    requests = {"value": 0}

    def submitlice(route) -> None:
        requests["value"] += 1
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": 0}',
        )

    page = browser.new_page()
    page.route("**/permit/web/permit/submitlice", submitlice)
    page.route(
        "**/permit/web/permit/savelicepic",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": 0, "data": "server-file.jpg"}',
        ),
    )
    page.set_content(
        """
        <base href="https://fkzhunru.baidu.com/">
        <div>URL信息</div>
        <div id="tabs"><button>业务1</button><button>业务2</button></div>
        <section id="card-1" class="business-card">
          <div class="main-area">
            <h2>业务1</h2>
            <div class="business-field"><span>*</span><span>经营业务</span><span>推广审查</span></div>
            <div class="forms"><div class="file-form form-card" style="width:60%">
                  <input type="file" multiple style="display:none"><span>举证链接</span><input class="evidence">
            </div></div>
          </div>
          <div class="supplement-area">
            <label><input class="supplement" type="checkbox">我还需要补充其他资质</label>
            <button class="more">新增补充资质</button>
          </div>
        </section>
        <section id="card-2" class="business-card">
          <div class="main-area">
            <h2>业务2</h2>
            <div class="business-field"><span>经营业务</span><span>三类医疗器械（不可个人，B）</span></div>
            <div class="forms"><div class="file-form form-card" style="width:60%">
                  <input type="file" multiple style="display:none"><span>举证链接</span><input class="evidence">
            </div></div>
          </div>
          <div class="supplement-area">
            <label><input class="supplement" type="checkbox">我还需要补充其他资质</label>
            <button class="more">新增补充资质</button>
          </div>
        </section>
        <script>
          function bindForm(form) {
            form.querySelector('input[type="file"]').addEventListener(
              'change', async event => {
                for (const file of event.target.files) {
                  await fetch('/permit/web/permit/savelicepic', {method: 'POST'});
                }
              }
            );
            form.addEventListener('mouseleave', () => {
              if (form.querySelector('input[type="file"]').files.length) {
                fetch('/permit/web/permit/submitlice', {method: 'POST'});
              }
            });
          }
          function addForm(card) {
            const form = document.createElement('div');
            form.className = 'file-form form-card';
            form.style.width = '60%';
                form.innerHTML = '<input type="file" multiple style="display:none">' +
              '<span>举证链接</span><input class="evidence">';
            card.querySelector('.forms').appendChild(form);
            bindForm(form);
          }
          document.querySelectorAll('.business-card').forEach(card => {
            bindForm(card.querySelector('.file-form'));
            card.querySelector('.supplement').addEventListener('change', () => addForm(card));
            card.querySelector('.more').addEventListener('click', () => {
              const files = card.querySelectorAll('input[type="file"]');
              if (files[files.length - 1].files.length) addForm(card);
            });
          });
        </script>
        """
    )
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    third = tmp_path / "third.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    third.write_bytes(b"third")
    qualification = Qualification(
        index_name="资质1",
        qualification_no="",
        qualification_name="",
        expiry=Expiry(permanent=False),
        evidence_url="https://example.test/evidence",
        files=(first, second, third),
    )

    NewAuditQualificationPage(page, timeout=2_000).upload_type(
        QualificationType("三类医疗器械", (qualification,)),
        2,
    )

    assert page.locator("#card-1 input[type='file']").count() == 1
    assert page.locator("#card-1 input[type='file']").evaluate(
        "element => element.files.length"
    ) == 0
    assert page.locator("#card-2 input[type='file']").count() == 1
    assert page.locator("#card-2 input[type='file']").evaluate(
        "element => element.files.length"
    ) == 1
    assert page.locator("#card-2 .evidence").evaluate_all(
        "elements => elements.map(element => element.value)"
    ) == ["https://example.test/evidence"]
    assert requests["value"] == 1
    page.close()


def test_new_audit_does_not_use_global_promotion_review_text(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <div>推广审查</div>
        <div id="tabs">
          <span class="business-tab"><button>业务1</button></span>
          <span class="business-tab"><button>业务2</button><button aria-label="关闭业务2">×</button></span>
          <span class="business-tab"><button>业务3</button><button aria-label="关闭业务3">×</button></span>
          <span class="business-tab"><button>业务4</button><button aria-label="关闭业务4">×</button></span>
        </div>
        <section class="business-card">
          <h2>业务1</h2>
          <p>说明：推广审查是所有公司都需要提交的资质。</p>
          <div class="business-field"><span>经营业务</span><span>其他经营业务</span></div>
          <input type="file"><span>举证链接</span><input>
        </section>
        """
    )
    new_page = NewAuditQualificationPage(page, timeout=1_000)

    with pytest.raises(PageFlowError, match="唯一“推广审查”"):
        new_page.remove_default_extra_businesses()

    assert sorted(new_page._business_tabs()) == [1, 2, 3, 4]
    page.close()


def test_new_audit_adds_missing_promotion_and_removes_dynamic_defaults(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <div id="tabs">
          <span class="business-tab" data-index="1"><button>业务1</button><button aria-label="关闭业务1">×</button></span>
          <span class="business-tab" data-index="2"><button>业务2</button><button aria-label="关闭业务2">×</button></span>
          <span class="business-tab" data-index="3"><button>业务3</button><button aria-label="关闭业务3">×</button></span>
        </div>
        <button id="add-business">+ 新增业务资质</button>
        <div id="cards">
          <section class="business-card" data-index="1"><h2>业务1</h2><div class="business-field"><span>经营业务</span><span>入驻商城类（不可个人，C2）</span></div><input type="file"><span>举证链接</span><input><span>我还需要补充其他资质</span></section>
          <section class="business-card" data-index="2"><h2>业务2</h2><div class="business-field"><span>经营业务</span><span>三类医疗器械（不可个人，B）</span></div><input type="file"><span>举证链接</span><input><span>我还需要补充其他资质</span></section>
          <section class="business-card" data-index="3"><h2>业务3</h2><div class="business-field"><span>经营业务</span><span>电商代运营【房产承诺函传营业执照（如未要求提交承诺函请忽略）】</span></div><input type="file"><span>举证链接</span><input><span>我还需要补充其他资质</span></section>
        </div>
        <script>
          function bindClose(button) {
            button.addEventListener('click', () => {
              const index = button.parentElement.dataset.index;
              button.parentElement.remove();
              document.querySelector(`.business-card[data-index="${index}"]`).remove();
            });
          }
          document.querySelectorAll('[aria-label^="关闭业务"]').forEach(bindClose);
          document.querySelector('#add-business').addEventListener('click', () => {
            const tab = document.createElement('span');
            tab.className = 'business-tab';
            tab.dataset.index = '4';
            tab.innerHTML = '<button>业务4</button><button aria-label="关闭业务4">×</button>';
            bindClose(tab.querySelector('[aria-label]'));
            document.querySelector('#tabs').appendChild(tab);
            const card = document.createElement('section');
            card.className = 'business-card';
            card.dataset.index = '4';
            card.innerHTML = '<h2>业务4</h2><label>经营业务<input role="combobox" placeholder="请选择"></label><input type="file"><span>举证链接</span><input><span>我还需要补充其他资质</span>';
            document.querySelector('#cards').appendChild(card);
            const search = card.querySelector('[placeholder]');
            search.addEventListener('input', () => {
              const option = document.createElement('div');
              option.setAttribute('role', 'option');
              option.textContent = '推广审查';
              option.addEventListener('click', () => {
                search.value = option.textContent;
                option.remove();
              });
              document.body.appendChild(option);
            });
          });
        </script>
        """
    )
    qualification_type = QualificationType(
        "推广审查",
        (
            Qualification(
                index_name="资质1",
                qualification_no="",
                qualification_name="",
                expiry=Expiry(permanent=False),
                evidence_url=None,
                files=(Path("/tmp/promotion.jpg"),),
            ),
        ),
    )
    new_page = NewAuditQualificationPage(page, timeout=2_000)

    promotion_index = new_page.prepare_promotion_business(qualification_type)

    assert promotion_index == 4
    assert sorted(new_page._business_tabs()) == [4]
    assert new_page._business_type_matches(
        new_page._business_container(4),
        "推广审查",
    )
    page.close()


def test_new_audit_business_delete_never_clicks_unlabelled_svg(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <div id="tabs">
          <span class="business-tab"><button>业务1</button></span>
          <span id="business-2" class="business-tab">
            <button>业务2</button>
            <svg id="status-icon" onclick="window.statusIconClicked = true"></svg>
            <button aria-label="关闭业务2" onclick="this.parentElement.remove()">×</button>
          </span>
        </div>
        """
    )
    new_page = NewAuditQualificationPage(page, timeout=1_000)

    new_page._close_business_tab(2)

    assert page.evaluate("window.statusIconClicked") is None
    assert page.locator("#business-2").count() == 0
    page.close()


def test_new_audit_business_delete_uses_real_card_action(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <div id="tabs">
          <div class="item-tag"><span>业务1</span></div>
          <div id="tab-2" class="item-tag"><span>业务2</span></div>
        </div>
        <div class="business-form-card"><span>业务1</span><input type="file"></div>
        <div id="card-2" class="business-form-card">
          <span>业务2</span><input type="file">
          <button onclick="document.querySelector('#tab-2').remove(); this.parentElement.remove()">删除</button>
        </div>
        """
    )
    view = NewAuditQualificationPage(page, timeout=1_000)

    view._close_business_tab(2)

    assert sorted(view._business_tabs()) == [1]
    assert page.locator('#card-2').count() == 0
    page.close()


def test_detail_preflight_rejects_filled_card_without_edit_or_delete(
    browser,
) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务1： 推广审查</div>
          <div class="required-card" style="border: 1px dashed #ccc">
            <div>资质状态 待审核</div>
            <div>资质编号 旧编号</div>
            <div>资质名称 旧名称</div>
            <div>有效期至 2030-03-31</div>
            <div>举证链接 无</div>
          </div>
          <div>上传备用资质文件</div>
        </div>
        """
    )
    industry = IndustryQualificationPage(page, timeout=2_000)
    panel = industry.scan_businesses()[0]
    qualification = Qualification(
        index_name="资质1",
        qualification_no="新编号",
        qualification_name="新名称",
        expiry=Expiry(permanent=False, date=date(2031, 1, 1)),
        evidence_url=None,
        files=(),
    )
    runner = object.__new__(WorkflowRunner)

    with pytest.raises(PageFlowError, match="资质编辑入口无法唯一定位"):
        runner._preflight_existing_qualification_cards(
            industry,
            ((QualificationType("推广审查", (qualification,)), panel),),
        )

    assert industry.scan_cards(panel)[0].qualification_no == "旧编号"
    page.close()


def test_detail_preflight_rejects_disabled_edit_control(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务1： 推广审查</div>
          <div class="required-card" style="border: 1px dashed #ccc">
            <div>资质状态 待审核</div>
            <div>资质编号 旧编号</div>
            <div>资质名称 旧名称</div>
            <div>有效期至 2030-03-31</div>
            <div>举证链接 无</div>
            <span role="button" aria-disabled="true">
              <i class="el-icon-edit">编辑</i>
            </span>
          </div>
          <div>上传备用资质文件</div>
        </div>
        """
    )
    industry = IndustryQualificationPage(page, timeout=2_000)
    panel = industry.scan_businesses()[0]
    card = industry.scan_cards(panel)[0]

    with pytest.raises(PageFlowError, match="资质编辑入口无法唯一定位"):
        industry.validate_card_edit_target(panel, card)

    assert industry.scan_cards(panel)[0].qualification_no == "旧编号"
    page.close()


def test_detail_preflight_rejects_disabled_delete_control(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务1： 推广审查</div>
          <div class="backup-card" style="border: 1px dashed #ccc">
            <div>资质状态 待审核</div>
            <div>资质编号 旧编号</div>
            <div>资质名称 旧名称</div>
            <div>有效期至 2030-03-31</div>
            <div>举证链接 无</div>
            <button disabled><i class="el-icon-delete">删除</i></button>
          </div>
          <div>上传备用资质文件</div>
        </div>
        """
    )
    industry = IndustryQualificationPage(page, timeout=2_000)
    panel = industry.scan_businesses()[0]
    card = industry.scan_cards(panel)[0]

    with pytest.raises(PageFlowError, match="旧资质删除入口无法唯一定位"):
        industry.validate_card_deletion_target(panel, card)

    assert industry.scan_cards(panel)[0].qualification_no == "旧编号"
    page.close()


def test_scan_businesses_and_qualification_cards_from_local_html(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务1： 推广审查</div>
          <div class="content">
            <div class="card" style="border: 1px dashed #ccc">
              <div>资质状态 待提交</div>
              <div>资质编号 编号A</div>
              <div>资质名称 名称A</div>
              <div>有效期至 2027-01-10</div>
              <div>举证链接 无</div>
              <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
                   alt="server-a.jpg">
              <i class="el-icon-delete"></i>
            </div>
            <div>上传备用资质文件</div>
          </div>
        </div>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务2： 三类医疗器械（不可个人，B）
            <span>删除业务</span>
          </div>
        </div>
        """
    )
    industry = IndustryQualificationPage(page, timeout=2_000)

    panels = industry.scan_businesses()
    cards = industry.scan_cards(panels[0])

    assert [item.display_name for item in panels] == [
        "推广审查",
        "三类医疗器械（不可个人，B）",
    ]
    assert panels[1].deletable is True
    assert len(cards) == 1
    assert cards[0].qualification_no == "编号A"
    assert cards[0].qualification_name == "名称A"
    assert cards[0].file_identifiers == ("server-a.jpg",)
    page.close()


def test_upload_ocr_permanent_verification_and_submit_with_local_html(
    browser,
    tmp_path: Path,
) -> None:
    upload_counter = {"value": 0}

    def route_handler(route) -> None:
        if route.request.url.endswith("/permit/web/permit/savelicepic"):
            upload_counter["value"] += 1
            payload = {
                "status": 0,
                "message": "success",
                "data": f"server-{upload_counter['value']}.jpg",
            }
        elif route.request.url.endswith("/permit/web/permit/submitlice"):
            payload = {"status": 0, "message": "success", "data": 0}
        else:
            route.continue_()
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            headers={"access-control-allow-origin": "*"},
            body=json.dumps(payload),
        )

    page = browser.new_page()
    page.route("**/permit/web/permit/**", route_handler)
    page.set_content(
        """
        <base href="https://fkzhunru.baidu.com/">
        <div class="el-dialog">
          <div class="el-form-item">上传资质文件<input id="files" type="file"></div>
          <ul class="el-upload-list"></ul>
          <div class="el-form-item">资质编号<input></div>
          <div class="el-form-item">资质名称<input></div>
          <div class="el-form-item">有效期至<input id="expiry"></div>
          <label><input id="permanent" type="checkbox"><span>永久</span></label>
          <div class="el-form-item">举证链接<input></div>
          <button id="submit">提交</button>
        </div>
        <script>
          const fileInput = document.querySelector('#files');
          fileInput.addEventListener('change', async () => {
            const response = await fetch('/permit/web/permit/savelicepic', {method: 'POST'});
            const payload = await response.json();
            const item = document.createElement('li');
            item.className = 'el-upload-list__item';
            item.dataset.uploadFile = payload.data;
            item.innerHTML = `<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
              alt="${payload.data}"><button class="el-icon-close">x</button>`;
            item.querySelector('button').addEventListener('click', () => item.remove());
            document.querySelector('.el-upload-list').appendChild(item);
            const prompt = document.createElement('div');
            prompt.className = 'el-message-box';
            prompt.setAttribute('role', 'dialog');
            prompt.innerHTML = '<span>OCR未识别到数据，请补充资质信息</span><button>好的</button>';
            prompt.querySelector('button').addEventListener('click', () => prompt.remove());
            document.body.appendChild(prompt);
          });
          document.querySelector('#permanent').addEventListener('change', event => {
            document.querySelector('#expiry').disabled = event.target.checked;
          });
          document.querySelector('#submit').addEventListener('click', async () => {
            await fetch('/permit/web/permit/submitlice', {method: 'POST'});
            document.querySelector('.el-dialog').style.display = 'none';
          });
        </script>
        """
    )
    first_file = tmp_path / "first.jpg"
    second_file = tmp_path / "second.jpg"
    first_file.write_bytes(b"first")
    second_file.write_bytes(b"second")
    qualification = Qualification(
        index_name="资质1",
        qualification_no="编号1",
        qualification_name="名称1",
        expiry=Expiry(permanent=True, date=None),
        evidence_url=None,
        files=(first_file, second_file),
    )
    dialog = page.locator(".el-dialog")
    form = QualificationForm(page, dialog, timeout=5_000)

    uploaded_ids = form.upload_files(qualification)
    form.fill_from_input(qualification)
    form.submit(qualification)

    assert uploaded_ids == ("server-1.jpg", "server-2.jpg")
    assert page.locator(".el-message-box").count() == 0
    assert dialog.is_hidden()
    page.close()


def test_clear_existing_files_requires_verified_zero_count(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <div class="el-dialog">
          <ul class="el-upload-list">
            <li class="el-upload-list__item">
              <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==">
              <button class="el-icon-close">x</button>
            </li>
          </ul>
        </div>
        <script>
          document.querySelector('.el-icon-close').addEventListener(
            'click',
            event => event.target.closest('li').remove()
          );
        </script>
        """
    )
    form = QualificationForm(page, page.locator(".el-dialog"), timeout=2_000)

    form.clear_existing_files(expected_count=1)

    assert page.locator(".el-upload-list__item").count() == 0
    page.close()


def test_expiry_date_is_pasted_without_using_date_picker(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <div class="el-dialog">
          <div class="el-form-item">资质编号<input></div>
          <div class="el-form-item">资质名称<input></div>
          <div class="el-form-item">有效期至<input id="expiry"></div>
          <label><input id="permanent" type="checkbox"><span>永久</span></label>
          <div class="el-form-item">举证链接<input></div>
          <div class="date-picker"><button class="date-option">2027-01-10</button></div>
        </div>
        <script>
          window.dateOptionClicks = 0;
          document.querySelector('.date-option').addEventListener(
            'click',
            () => window.dateOptionClicks += 1
          );
        </script>
        """
    )
    qualification = Qualification(
        index_name="资质1",
        qualification_no="编号1",
        qualification_name="名称1",
        expiry=Expiry(permanent=False, date=date(2027, 1, 10)),
        evidence_url=None,
        files=(),
    )
    form = QualificationForm(page, page.locator(".el-dialog"), timeout=2_000)

    form.fill_from_input(qualification)

    assert page.locator("#expiry").input_value() == "2027-01-10"
    assert page.locator("#permanent").is_checked() is False
    assert page.evaluate("window.dateOptionClicks") == 0
    page.close()


def test_delete_card_accepts_generic_confirmation_without_qualification_number(
    browser,
) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务1： 推广审查</div>
          <div class="card" style="border: 1px dashed #ccc">
            <div>资质状态 待提交</div>
            <div>资质编号 编号A</div>
            <div>资质名称 名称A</div>
            <div>有效期至 2027-01-10</div>
            <div>举证链接 无</div>
            <button class="el-icon-delete">删除</button>
          </div>
          <div>上传备用资质文件</div>
        </div>
        <script>
          document.querySelector('.el-icon-delete').addEventListener('click', () => {
            const dialog = document.createElement('div');
            dialog.className = 'el-message-box';
            dialog.setAttribute('role', 'dialog');
            dialog.innerHTML =
              '<div>是否确认删除该资质？</div><button class="cancel">取消</button>' +
              '<button class="confirm">确定</button>';
            dialog.querySelector('.cancel').addEventListener('click', () => dialog.remove());
            dialog.querySelector('.confirm').addEventListener('click', () => {
              document.querySelector('.card').remove();
              dialog.remove();
            });
            document.body.appendChild(dialog);
          });
        </script>
        """
    )
    industry = IndustryQualificationPage(page, timeout=2_000)
    panel = industry.scan_businesses()[0]
    card = industry.scan_cards(panel)[0]

    industry.delete_card(panel, card)

    assert industry.scan_cards(panel) == ()
    page.close()


def test_delete_card_keeps_non_deletable_card_with_same_identity(browser) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务1： 二类医疗器械（不可个人，B）</div>
          <div class="required-card" style="border: 1px dashed #ccc">
            <div>资质状态 待提交</div>
            <div>资质编号 相同编号</div>
            <div>资质名称 相同名称</div>
            <div>有效期至 2030-03-31</div>
            <div>举证链接 无</div>
            <button class="el-icon-edit">编辑</button>
          </div>
          <div class="backup-card" style="border: 1px dashed #ccc">
            <div>资质状态 待提交</div>
            <div>资质编号 相同编号</div>
            <div>资质名称 相同名称</div>
            <div>有效期至 永久</div>
            <div>举证链接 无</div>
            <button class="el-icon-delete">删除</button>
          </div>
          <div>上传备用资质文件</div>
        </div>
        <script>
          document.querySelector('.backup-card .el-icon-delete').addEventListener(
            'click',
            () => {
              const dialog = document.createElement('div');
              dialog.className = 'el-message-box';
              dialog.setAttribute('role', 'dialog');
              dialog.innerHTML =
                '<div>是否确认删除该资质？</div><button class="confirm">确定</button>';
              dialog.querySelector('.confirm').addEventListener('click', () => {
                document.querySelector('.backup-card').remove();
                dialog.remove();
              });
              document.body.appendChild(dialog);
            }
          );
        </script>
        """
    )
    industry = IndustryQualificationPage(page, timeout=2_000)
    panel = industry.scan_businesses()[0]
    cards = industry.scan_cards(panel)
    deletable = next(card for card in cards if card.deletable)

    industry.delete_card(panel, deletable)

    remaining = industry.scan_cards(panel)
    assert len(remaining) == 1
    assert remaining[0].qualification_no == "相同编号"
    assert remaining[0].qualification_name == "相同名称"
    assert remaining[0].deletable is False
    page.close()


def test_waits_for_submitted_card_to_finish_async_render(
    browser,
    tmp_path: Path,
) -> None:
    page = browser.new_page()
    page.set_content(
        """
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">经营业务1： 推广审查</div>
          <div class="cards"></div>
          <div>上传备用资质文件</div>
        </div>
        <script>
          setTimeout(() => {
            document.querySelector('.cards').innerHTML = `
              <div class="card" style="border: 1px dashed #ccc">
                <div>资质状态 待提交</div>
                <div>资质编号 编号A</div>
                <div>资质名称 名称A</div>
                <div>有效期至 2027-01-10</div>
                <div>举证链接 无</div>
                <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==">
              </div>`;
          }, 400);
        </script>
        """
    )
    file_path = tmp_path / "qualification.jpg"
    file_path.write_bytes(b"qualification")
    qualification = Qualification(
        index_name="资质1",
        qualification_no="编号A",
        qualification_name="名称A",
        expiry=Expiry(permanent=False, date=date(2027, 1, 10)),
        evidence_url=None,
        files=(file_path,),
    )
    industry = IndustryQualificationPage(page, timeout=2_000)
    panel = industry.scan_businesses()[0]
    runner = object.__new__(WorkflowRunner)
    runner.config = WorkflowConfig(page_timeout_ms=2_000)

    card = runner._wait_for_submitted_qualification(
        industry,
        panel,
        qualification,
    )

    assert card.qualification_no == "编号A"
    assert card.file_count == 1
    page.close()


def test_new_business_uses_visible_inline_required_qualification_form(
    browser,
) -> None:
    def route_handler(route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            headers={"access-control-allow-origin": "*"},
            body=json.dumps({"status": 0, "message": "success", "data": 0}),
        )

    page = browser.new_page()
    page.route("**/permit/web/permit/submitlice", route_handler)
    page.set_content(
        """
        <base href="https://local.test/">
        <h2>行业资质</h2>
        <div class="el-collapse-item">
          <div class="el-collapse-item__header">
            经营业务1： 一类医疗器械（不可个人，B）
          </div>
          <div class="inline-form" style="border: 1px dashed #ccc">
            <div class="el-form-item">上传资质文件<input type="file"></div>
            <div class="el-form-item">资质编号<input></div>
            <div class="el-form-item">资质名称<input></div>
            <div class="el-form-item">有效期至<input></div>
            <label><input type="checkbox">永久</label>
            <div class="el-form-item">举证链接<input></div>
            <button>提交</button>
          </div>
          <div>上传备用资质文件</div>
        </div>
        <script>
          window.inlineCardClicks = 0;
          document.querySelector('.inline-form').addEventListener(
            'click',
            () => window.inlineCardClicks += 1
          );
          document.querySelector('.inline-form button').addEventListener(
            'click',
            async event => {
              event.stopPropagation();
              await fetch('/permit/web/permit/submitlice', {method: 'POST'});
              document.querySelector('.inline-form').innerHTML =
                '<div>资质状态 待提交</div><div>资质编号 编号A</div>' +
                '<div>资质名称 名称A</div><div>有效期至 2027-01-10</div>' +
                '<div>举证链接 无</div>';
            }
          );
        </script>
        """
    )
    industry = IndustryQualificationPage(page, timeout=500)
    panel = industry.scan_businesses()[0]
    empty_card = industry.scan_cards(panel)[0]

    form_root = industry.open_new_qualification(panel, empty_card=empty_card)

    assert form_root.get_attribute("class") == "inline-form"
    assert page.evaluate("window.inlineCardClicks") == 0
    assert page.locator(".el-dialog").count() == 0

    qualification = Qualification(
        index_name="资质1",
        qualification_no="编号A",
        qualification_name="名称A",
        expiry=Expiry(permanent=False, date=date(2027, 1, 10)),
        evidence_url=None,
        files=(),
    )
    form = QualificationForm(page, form_root, timeout=2_000)
    form.fill_from_input(qualification)
    form.submit(qualification)

    assert form_root.locator("input").count() == 0
    assert "资质编号 编号A" in form_root.inner_text()
    page.close()


def test_submit_all_clicks_confirmation_and_validates_success(browser) -> None:
    request_count = {"value": 0}

    def route_handler(route) -> None:
        request_count["value"] += 1
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": 0, "message": "success", "data": ""}),
        )

    page = browser.new_page()
    page.route("**/permit/web/permit/submitall", route_handler)
    page.set_content(
        """
        <base href="https://fkzhunru.baidu.com/">
        <button id="submit-all">本模块提交</button>
        <script>
          document.querySelector('#submit-all').addEventListener('click', () => {
            const dialog = document.createElement('div');
            dialog.className = 'el-message-box';
            dialog.innerHTML =
              '<div>是否确认提交本模块？</div><button class="cancel">取消</button>' +
              '<button class="confirm">确定</button>';
            dialog.querySelector('.confirm').addEventListener('click', async () => {
              await fetch('/permit/web/permit/submitall', {method: 'POST'});
              dialog.remove();
            });
            document.body.appendChild(dialog);
          });
        </script>
        """
    )

    submit_all_qualifications(page, timeout=2_000)

    assert request_count["value"] == 1
    page.close()


@pytest.mark.parametrize("confirmation_delay", [0, 3500])
def test_new_audit_start_review_confirms_and_validates_submitall(browser, confirmation_delay) -> None:
    request_count = {"value": 0}

    def route_handler(route) -> None:
        request_count["value"] += 1
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": 0, "message": "success"}),
        )

    page = browser.new_page()
    page.route("**/permit/web/permit/submitall", route_handler)
    page.set_content(
        """
        <base href="https://fkzhunru.baidu.com/">
        <button id="start-review">发起审核</button>
        <script>
          document.querySelector('#start-review').addEventListener('click', () => {
            const dialog = document.createElement('div');
            dialog.className = 'el-message-box';
            dialog.innerHTML =
              '<div>确认发起审核？</div><button>取消</button><button class="confirm">确定</button>';
            dialog.querySelector('.confirm').addEventListener('click', async () => {
              await fetch('/permit/web/permit/submitall', {method: 'POST'});
              dialog.remove();
            });
            setTimeout(() => document.body.appendChild(dialog), CONFIRMATION_DELAY);
          });
        </script>
        """.replace("CONFIRMATION_DELAY", str(confirmation_delay))
    )

    submit_all_qualifications(page, timeout=5_000)

    assert request_count["value"] == 1
    assert page.locator(".el-message-box").count() == 0
    page.close()


def test_submit_all_rejects_business_failure(browser) -> None:
    def route_handler(route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"status": 1, "message": "资质未完成", "data": ""}),
        )

    page = browser.new_page()
    page.route("**/permit/web/permit/submitall", route_handler)
    page.set_content(
        """
        <base href="https://fkzhunru.baidu.com/">
        <button id="submit-all">全部提交</button>
        <script>
          document.querySelector('#submit-all').addEventListener('click', async () => {
            await fetch('/permit/web/permit/submitall', {method: 'POST'});
          });
        </script>
        """
    )

    with pytest.raises(PageFlowError, match="资质未完成"):
        submit_all_qualifications(page, timeout=4_000)

    page.close()


def test_submit_all_rejects_non_200_success_response(browser) -> None:
    def route_handler(route) -> None:
        route.fulfill(
            status=201,
            content_type="application/json",
            body=json.dumps({"status": 0, "message": "created"}),
        )

    page = browser.new_page()
    page.route("**/permit/web/permit/submitall", route_handler)
    page.set_content(
        """
        <base href="https://fkzhunru.baidu.com/">
        <button id="submit-all">发起审核</button>
        <script>
          document.querySelector('#submit-all').addEventListener('click', async () => {
            await fetch('/permit/web/permit/submitall', {method: 'POST'});
          });
        </script>
        """
    )

    with pytest.raises(PageFlowError, match="HTTP 201"):
        submit_all_qualifications(page, timeout=4_000)

    page.close()


@pytest.mark.parametrize('failures,expected_calls', [(0, 1), (1, 2), (3, 4), (4, 4)])
def test_upload_retries_only_when_card_has_no_new_file(browser, tmp_path, failures, expected_calls, caplog):
    from src.upload_retry import upload_with_retry
    page = browser.new_page()
    calls = []
    def serve(route):
        calls.append(1)
        route.fulfill(status=503 if len(calls) <= failures else 200,
                      content_type='application/json', body='{"status":0}')
    page.route('https://fkzhunru.baidu.com/permit/web/permit/savelicepic', serve)
    page.set_content('''<input type="file"><div id="files"></div><script>
    document.querySelector('input').onchange=async()=>{
      const r=await fetch('https://fkzhunru.baidu.com/permit/web/permit/savelicepic',{method:'POST'});
      if(r.ok) document.querySelector('#files').appendChild(document.createElement('img'));
    };</script>''')
    file = tmp_path/'测试图片.png'; file.write_bytes(b'image')
    def trigger():
        page.locator('input').evaluate("e=>{e.value=''}")
        page.locator('input').set_input_files(str(file))
    def validate(response):
        if response.status != 200:
            raise PageFlowError('HTTP failure')
    caplog.set_level('INFO')
    try:
        if failures == 4:
            with pytest.raises(PageFlowError, match='已重试 3 次'):
                upload_with_retry(page, trigger, lambda: page.locator('#files img').count(), validate,
                                  description='业务[推广审查] 资质[资质1] 文件[测试图片.png]', timeout_ms=500)
        else:
            upload_with_retry(page, trigger, lambda: page.locator('#files img').count(), validate,
                              description='业务[推广审查] 资质[资质1] 文件[测试图片.png]', timeout_ms=500)
            assert page.locator('#files img').count() == 1
        assert len(calls) == expected_calls
        assert '资质[资质1]' in caplog.text
        assert not page._impl_obj.listeners('request')
        assert not page._impl_obj.listeners('response')
    finally:
        page.close()


def test_upload_error_with_existing_preview_does_not_retry(browser, tmp_path):
    from src.upload_retry import upload_with_retry
    page=browser.new_page(); calls=[]
    def serve(route):
        calls.append(1)
        route.fulfill(status=503,body='failed')
    page.route('https://fkzhunru.baidu.com/permit/web/permit/savelicepic',serve)
    page.set_content('''<input type="file"><div id="files"></div><script>
    document.querySelector('input').onchange=async()=>{
      await fetch('https://fkzhunru.baidu.com/permit/web/permit/savelicepic',{method:'POST'});
      setTimeout(()=>document.querySelector('#files').appendChild(document.createElement('img')),100);
    };</script>''')
    file=tmp_path/'proof.png'; file.write_bytes(b'image')
    def validate(response):
        raise PageFlowError('response failed')
    with pytest.raises(PageFlowError, match='缺少完整成功上传凭据'):
        upload_with_retry(page, lambda:page.locator('input').set_input_files(str(file)),
                          lambda:page.locator('#files img').count(),validate,
                          description='资质1/proof.png',timeout_ms=500)
    assert len(calls)==1
    page.close()


def test_upload_unknown_preview_does_not_retry_selected_input(browser, tmp_path):
    from src.upload_retry import upload_with_retry
    page=browser.new_page(); page.set_content('<input type="file">')
    file=tmp_path/'proof.png'; file.write_bytes(b'image'); calls=[]
    def trigger():
        calls.append(1); page.locator('input').set_input_files(str(file))
    with pytest.raises(PageFlowError, match='无法确认文件缺失'):
        upload_with_retry(page,trigger,lambda:None,lambda response:None,
                          description='资质1/proof.png',timeout_ms=200)
    assert len(calls)==1
    assert page.locator('input').evaluate('e=>e.files.length')==1
    page.close()


def test_pending_upload_is_not_retried(browser, tmp_path):
    from src.upload_retry import upload_with_retry
    page=browser.new_page(); routes=[]
    page.route('https://fkzhunru.baidu.com/permit/web/permit/savelicepic',lambda route:routes.append(route))
    page.set_content('''<input type="file"><script>
    document.querySelector('input').onchange=()=>fetch('https://fkzhunru.baidu.com/permit/web/permit/savelicepic',{method:'POST'});
    </script>''')
    file=tmp_path/'proof.png'; file.write_bytes(b'image')
    with pytest.raises(PageFlowError, match='请求仍在执行'):
        upload_with_retry(page,lambda:page.locator('input').set_input_files(str(file)),lambda:0,
                          lambda response:None,description='资质1/proof.png',timeout_ms=300)
    assert len(routes)==1
    routes[0].abort()
    page.close()


@pytest.mark.parametrize("mode", ["missing", "delayed", "partial", "aborted", "no_request"])
def test_upload_uncertain_results_never_reupload(browser, tmp_path, mode):
    from src.upload_retry import upload_with_retry
    page = browser.new_page()
    calls = []
    def serve(route):
        calls.append(1)
        if mode == "aborted":
            route.abort()
        else:
            route.fulfill(status=503 if mode == "partial" and len(calls) == 2 else 200,
                          content_type="application/json", body='{"status":0}')
    page.route("**/permit/web/permit/savelicepic", serve)
    page.set_content('''<base href="https://fkzhunru.baidu.com/">
      <input type="file" multiple><div id="files"></div><script>
      window.mode = MODE;
      document.querySelector('input').onchange = async event => {
        if (window.mode === 'no_request') return;
        for (const file of event.target.files) {
          await fetch('/permit/web/permit/savelicepic', {method:'POST'}).catch(()=>{});
        }
        if (window.mode === 'delayed')
          setTimeout(()=>document.querySelector('#files').appendChild(document.createElement('img')), 150);
      };</script>'''.replace('MODE', json.dumps(mode)))
    file = tmp_path / "proof.png"
    file.write_bytes(b'image')
    triggers = []
    def trigger():
        triggers.append(1)
        page.locator('input').evaluate("e=>{e.value=''}")
        page.locator('input').set_input_files([str(file)] * (2 if mode == "partial" else 1))
    def validate(response):
        if response.status != 200:
            raise PageFlowError('HTTP failure')
    try:
        if mode == "delayed":
            result = upload_with_retry(page, trigger, lambda:page.locator('#files img').count(),
                                       validate, description='回填', timeout_ms=400)
            assert len(result) == 1
        else:
            with pytest.raises(PageFlowError, match='不重复上传'):
                upload_with_retry(page, trigger, lambda:page.locator('#files img').count(),
                                  validate, description='回填', timeout_ms=400,
                                  file_count=2 if mode == "partial" else 1)
        assert len(triggers) == 1
        assert not page._impl_obj.listeners('request')
    finally:
        page.close()


@pytest.mark.parametrize("preview_removed", [False, True])
def test_new_audit_saved_preview_missing_is_rejected(browser, preview_removed):
    page = browser.new_page()
    page.set_content('<div class="form-card"><div class="preview-container">'
                     '<span class="file-count">1/9</span></div></div>')
    view = NewAuditQualificationPage(page, timeout=300)
    if preview_removed:
        page.locator('.preview-container').evaluate('element => element.remove()')
    with pytest.raises(PageFlowError, match='保存后页面文件不完整或未显示'):
        view._verify_saved_file_count(page.locator('.form-card'), 2, '资质1', required=True)
    page.close()


def test_new_audit_saved_nested_preview_containers_are_valid(browser):
    page = browser.new_page()
    page.set_content('<div class="form-card"><div class="preview-container">'
                     '<div class="preview-container"><img></div>'
                     '<div class="preview-container"><img></div>'
                     '<div class="preview-container"><img></div>'
                     '<span class="file-count">3/4</span></div></div>')
    view = NewAuditQualificationPage(page, timeout=300)
    view._verify_saved_file_count(page.locator('.form-card'), 3, '资质1', required=True)
    page.close()


@pytest.mark.parametrize('mode', ['correct', 'duplicate_id', 'wrong_content', 'unloaded'])
def test_new_audit_checks_file_identity_and_content(browser, tmp_path, mode):
    import hashlib
    from io import BytesIO
    from PIL import Image
    from src.upload_identity import UploadReceipt
    page = browser.new_page()
    receipts = []
    images = {}
    for index, color in enumerate(('red', 'blue', 'green')):
        buf = BytesIO()
        Image.new('RGB', (3, 3), color).save(buf, format='PNG')
        path = tmp_path / f'{index}.png'
        path.write_bytes(buf.getvalue())
        images[f'{index}.png'] = buf.getvalue()
        receipts.append(UploadReceipt(path, hashlib.sha256(buf.getvalue()).hexdigest(), f'{index}.png'))
    def serve(route):
        from urllib.parse import parse_qs, urlsplit
        name = parse_qs(urlsplit(route.request.url).query)['filename'][0]
        if mode == 'unloaded':
            route.fulfill(status=404)
        else:
            body = images['1.png'] if mode == 'wrong_content' and name == '0.png' else images[name]
            route.fulfill(content_type='image/png', body=body)
    page.route('**/file?filename=*', serve)
    page.route('https://fkzhunru.baidu.com/test', lambda route:route.fulfill(content_type='text/html', body='<div class="form-card"></div>'))
    page.goto('https://fkzhunru.baidu.com/test')
    ids = ['1.png', '1.png', '2.png'] if mode == 'duplicate_id' else ['0.png', '1.png', '2.png']
    page.locator('.form-card').evaluate('''(card, ids) => {
      card.innerHTML = '<div class="preview-container"><span class="file-count">3/9</span>' +
        ids.map(id => '<li class="preview-list-li"><img src="/file?filename=' + id + '"></li>').join('') + '</div>';
    }''', ids)
    view = NewAuditQualificationPage(page, timeout=1800)
    try:
        if mode == 'correct':
            view._verify_file_receipts(lambda:page.locator('.form-card'), receipts, '资质3', content=True)
        else:
            with pytest.raises(PageFlowError, match='身份|内容'):
                view._verify_file_receipts(lambda:page.locator('.form-card'), receipts, '资质3', content=True)
    finally:
        page.close()


def test_new_audit_background_page_can_trigger_autosave(browser, monkeypatch):
    context = browser.new_context()
    page = context.new_page()
    page.set_content('''<section style="width:900px;height:500px">
      <div id="card" style="width:400px;height:200px">资质卡片</div></section>
      <script>window.savedWithFocus=false;
      document.querySelector('#card').onmouseleave=()=>{
        if(document.hasFocus())window.savedWithFocus=true;
      };</script>''')
    other = context.new_page()
    other.bring_to_front()
    # 模拟 bring_to_front 无法使桌面后台窗口获得 OS 焦点；用真实 CDP 提供焦点。
    monkeypatch.setattr(page, 'bring_to_front', lambda: None)
    view = NewAuditQualificationPage(page, timeout=3000)
    view._click_blank_outside_card(page.locator('#card'), page.locator('section'))
    assert page.evaluate('document.hasFocus()')
    assert page.evaluate('window.savedWithFocus')
    context.close()
