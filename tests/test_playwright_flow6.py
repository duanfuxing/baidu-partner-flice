from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.errors import PageFlowError, QualificationPendingReview
from src.industry_qualification import IndustryQualificationPage
from src.models import Expiry, Qualification
from src.qualification_form import QualificationForm
from src.workflow import (
    WorkflowConfig,
    WorkflowRunner,
    select_url_and_open_industry_qualification,
    submit_all_qualifications,
)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel="chrome", headless=True)
        yield instance
        instance.close()


def test_pending_review_url_is_rejected_before_clicking_view(browser) -> None:
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
            () => window.viewClicked = true
          );
        </script>
        """
    )

    with pytest.raises(QualificationPendingReview) as captured:
        select_url_and_open_industry_qualification(
            page,
            target_url,
            timeout=2_000,
        )

    assert captured.value.error_code == "qualification-pending-review"
    assert page.evaluate("window.viewClicked") is False
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
        <base href="https://local.test/">
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
        <base href="https://local.test/">
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
        <base href="https://local.test/">
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
