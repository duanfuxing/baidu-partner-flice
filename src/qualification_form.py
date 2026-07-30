"""资质弹窗上传、OCR处理、字段覆盖和提交。"""

from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

from .errors import PageFlowError
from .industry_qualification import QualificationCardSnapshot
from .models import Qualification


def _clean_card_value(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value)


def qualification_matches(
    card: QualificationCardSnapshot,
    qualification: Qualification,
    expected_file_identifiers: tuple[str, ...] | None = None,
) -> bool:
    if not qualification_fields_and_file_count_match(card, qualification):
        return False
    if not qualification.files:
        return True
    if not expected_file_identifiers:
        # 文件数量相同不足以证明历史文件内容一致。
        return False
    actual = {_clean_card_value(item) for item in card.file_identifiers}
    expected = {_clean_card_value(item) for item in expected_file_identifiers}
    return expected.issubset(actual)


def qualification_fields_and_file_count_match(
    card: QualificationCardSnapshot,
    qualification: Qualification,
) -> bool:
    """校验本次提交后的可见字段和文件数，不比较不同格式的文件 URL/ID。"""

    expected_expiry = "永久" if qualification.expiry.permanent else qualification.expiry.date.isoformat()
    expected_evidence = qualification.evidence_url or ""
    scalar_fields_match = (
        _clean_card_value(card.qualification_no) == _clean_card_value(qualification.qualification_no)
        and _clean_card_value(card.qualification_name)
        == _clean_card_value(qualification.qualification_name)
        and _clean_card_value(card.expiry_text) == _clean_card_value(expected_expiry)
        and _clean_card_value("" if card.evidence_url == "无" else card.evidence_url)
        == _clean_card_value(expected_evidence)
    )
    return scalar_fields_match and card.file_count == len(qualification.files)


class QualificationForm:
    def __init__(self, page, dialog, timeout: int = 30_000) -> None:
        self.page = page
        self.dialog = dialog
        self.timeout = timeout
        self.inline = (
            dialog.locator(
                "xpath=ancestor-or-self::*[contains(@class,'el-dialog') or @role='dialog']"
            ).count()
            == 0
        )

    def _input(self, label: str):
        form_item = self.dialog.locator(".el-form-item").filter(has_text=label)
        if form_item.count():
            input_locator = form_item.first.locator("input")
            if input_locator.count():
                return input_locator.first
        label_locator = self.dialog.get_by_text(label, exact=True)
        if label_locator.count():
            input_locator = label_locator.first.locator("xpath=following::input[1]")
            if input_locator.count():
                return input_locator.first
        raise PageFlowError(f"资质弹窗找不到字段：{label}")

    def _fill_input(self, label: str, value: str) -> None:
        locator = self._input(label)
        try:
            locator.fill(value)
        except Exception:
            locator.evaluate(
                """(element, value) => {
                    const setter = Object.getOwnPropertyDescriptor(
                      HTMLInputElement.prototype, 'value'
                    ).set;
                    setter.call(element, value);
                    element.dispatchEvent(new Event('input', {bubbles: true}));
                    element.dispatchEvent(new Event('change', {bubbles: true}));
                    element.dispatchEvent(new Event('blur', {bubbles: true}));
                }""",
                value,
            )

    def _paste_expiry_date(self, value: str) -> None:
        """直接向日期输入框粘贴文本，不操作日期选择面板。"""

        locator = self._input("有效期至")
        try:
            locator.focus()
            locator.select_text()
            self.page.keyboard.insert_text(value)
            self.page.keyboard.press("Tab")
        except Exception:
            # 某些 Element UI 日期输入框会拦截键盘事件；仍只直接设置
            # 输入值并触发表单事件，不退回到日期面板选取。
            locator.evaluate(
                """(element, value) => {
                    const setter = Object.getOwnPropertyDescriptor(
                      HTMLInputElement.prototype, 'value'
                    ).set;
                    setter.call(element, value);
                    element.dispatchEvent(new Event('input', {bubbles: true}));
                    element.dispatchEvent(new Event('change', {bubbles: true}));
                    element.dispatchEvent(new Event('blur', {bubbles: true}));
                }""",
                value,
            )

    def upload_files(self, qualification: Qualification) -> tuple[str, ...]:
        file_input = self.dialog.locator('input[type="file"]')
        if file_input.count() == 0:
            raise PageFlowError("资质弹窗找不到文件上传控件")
        paths = [str(path.resolve()) for path in qualification.files]
        uploaded_identifiers: list[str] = []
        for path in paths:
            try:
                with self.page.expect_response(
                    lambda response: "/permit/web/permit/savelicepic" in response.url,
                    timeout=self.timeout,
                ) as response_info:
                    file_input.first.set_input_files(path)
                response = response_info.value
                if not response.ok:
                    raise PageFlowError(
                        f"资质文件上传接口 HTTP {response.status}：{Path(path).name}"
                    )
                payload = response.json()
                if payload.get("status") != 0 or not payload.get("data"):
                    raise PageFlowError(
                        f"资质文件上传失败：{Path(path).name}："
                        f"{payload.get('message') or payload.get('status')}"
                    )
                uploaded_identifiers.append(str(payload["data"]))
                self._handle_ocr_prompt()
                self.page.wait_for_timeout(300)
            except PageFlowError:
                raise
            except Exception as exc:
                raise PageFlowError(
                    f"资质文件上传未收到成功响应：{Path(path).name}"
                ) from exc
        if len(uploaded_identifiers) != len(paths):
            raise PageFlowError(
                f"资质文件上传数量不一致，期望 {len(paths)}，成功 {len(uploaded_identifiers)}"
            )
        return tuple(uploaded_identifiers)

    def _visible_upload_items(self):
        candidates = self.dialog.locator(
            ".el-upload-list__item, [data-upload-file], [class*='file-preview']"
        )
        return [
            candidates.nth(index)
            for index in range(candidates.count())
            if candidates.nth(index).is_visible()
        ]

    def clear_existing_files(self, expected_count: int) -> None:
        """编辑已有资质时移除旧文件，避免新旧文件叠加。"""

        items = self._visible_upload_items()
        if expected_count and len(items) != expected_count:
            raise PageFlowError(
                f"无法确认已有资质文件，卡片显示 {expected_count} 个，弹窗识别 {len(items)} 个"
            )
        delete_controls = self.dialog.locator(
            ".el-upload-list__item .el-icon-close, "
            ".el-upload-list__item-delete, "
            "[class*='upload-list'] [class*='delete']"
        )
        visible_controls = [
            delete_controls.nth(index)
            for index in range(delete_controls.count())
            if delete_controls.nth(index).is_visible()
        ]
        if items and len(visible_controls) < len(items):
            raise PageFlowError(
                f"已有资质文件删除入口不足，文件 {len(items)} 个，删除入口 {len(visible_controls)} 个"
            )
        for control in reversed(visible_controls):
            before = len(self._visible_upload_items())
            control.click(timeout=self.timeout)
            deadline = time.monotonic() + min(self.timeout, 5_000) / 1000
            while time.monotonic() < deadline:
                if len(self._visible_upload_items()) < before:
                    break
                self.page.wait_for_timeout(100)
            else:
                raise PageFlowError("删除已有资质文件后，文件列表未减少")
        if self._visible_upload_items():
            raise PageFlowError("编辑资质前未能清空全部旧文件")

    def _handle_ocr_prompt(self) -> None:
        prompt = self.page.get_by_text(
            re.compile(r"OCR未识别到数据|补充资质信息"),
            exact=False,
        )
        try:
            prompt.last.wait_for(state="visible", timeout=3_000)
        except Exception:
            # OCR 成功或页面没有提示时继续，字段仍会被 input.json 覆盖。
            self.page.wait_for_timeout(500)
            return
        self._dismiss_visible_ocr_prompt(prompt.last)

    def _dismiss_visible_ocr_prompt(self, prompt=None) -> None:
        if prompt is None:
            prompt = self.page.get_by_text(
                re.compile(r"OCR未识别到数据|补充资质信息"),
                exact=False,
            )
            visible = [
                prompt.nth(index)
                for index in range(prompt.count())
                if prompt.nth(index).is_visible()
            ]
            if not visible:
                return
            prompt = visible[-1]
        message_box = prompt.locator(
            "xpath=ancestor::*[contains(@class,'el-message-box') or @role='dialog'][1]"
        )
        okay = message_box.get_by_text("好的", exact=True)
        if okay.count() == 0:
            okay = self.page.get_by_text("好的", exact=True)
        if okay.count() == 0:
            raise PageFlowError("OCR提示出现，但找不到“好的”按钮")
        okay.last.click(timeout=self.timeout)

    def _permanent_checkbox(self):
        permanent_text = self.dialog.get_by_text("永久", exact=True)
        if permanent_text.count() == 0:
            raise PageFlowError("资质弹窗找不到“永久”选项")
        checkbox = permanent_text.first.locator(
            "xpath=ancestor::label[1]//input[@type='checkbox']"
        )
        if checkbox.count() == 0:
            checkbox = self.dialog.locator('input[type="checkbox"]').last
        if checkbox.count() == 0:
            raise PageFlowError("资质弹窗找不到“永久”复选框")
        return checkbox.first, permanent_text.first

    def _set_permanent(self, permanent: bool) -> None:
        checkbox, permanent_text = self._permanent_checkbox()
        checked = checkbox.is_checked()
        if checked != permanent:
            permanent_text.click(timeout=self.timeout)

    def _apply_fields(self, qualification: Qualification) -> None:
        self._dismiss_visible_ocr_prompt()
        self._fill_input("资质编号", qualification.qualification_no)
        self._fill_input("资质名称", qualification.qualification_name)
        self._set_permanent(qualification.expiry.permanent)
        if qualification.expiry.permanent:
            try:
                self._fill_input("有效期至", "")
            except PageFlowError:
                pass
        else:
            assert isinstance(qualification.expiry.date, date)
            self._paste_expiry_date(qualification.expiry.date.isoformat())
        self._fill_input("举证链接", qualification.evidence_url or "")

    def fill_from_input(self, qualification: Qualification) -> None:
        self._apply_fields(qualification)
        self.stabilize_and_verify(qualification)

    def verify_fields(self, qualification: Qualification) -> None:
        self._dismiss_visible_ocr_prompt()
        values = {
            "资质编号": self._input("资质编号").input_value().strip(),
            "资质名称": self._input("资质名称").input_value().strip(),
            "举证链接": self._input("举证链接").input_value().strip(),
        }
        expected = {
            "资质编号": qualification.qualification_no,
            "资质名称": qualification.qualification_name,
            "举证链接": qualification.evidence_url or "",
        }
        for label, expected_value in expected.items():
            if values[label] != expected_value:
                raise PageFlowError(
                    f"资质字段回读不一致：{label}，期望“{expected_value}”，实际“{values[label]}”"
                )
        checkbox, _ = self._permanent_checkbox()
        checked = checkbox.is_checked()
        if checked != qualification.expiry.permanent:
            raise PageFlowError(
                f"资质字段回读不一致：永久，期望 {qualification.expiry.permanent}，实际 {checked}"
            )
        date_input = self._input("有效期至")
        actual_date = date_input.input_value().strip()
        if qualification.expiry.permanent:
            if actual_date and not date_input.is_disabled():
                raise PageFlowError(
                    f"永久资质的有效期字段未清空或禁用，实际“{actual_date}”"
                )
        else:
            expected_date = qualification.expiry.date.isoformat()
            if actual_date != expected_date:
                raise PageFlowError(
                    f"资质字段回读不一致：有效期至，期望“{expected_date}”，实际“{actual_date}”"
                )

    def stabilize_and_verify(
        self,
        qualification: Qualification,
        *,
        stable_ms: int = 1_500,
        max_wait_ms: int = 10_000,
    ) -> None:
        deadline = time.monotonic() + max_wait_ms / 1000
        stable_since: float | None = None
        while time.monotonic() < deadline:
            self._dismiss_visible_ocr_prompt()
            try:
                self.verify_fields(qualification)
            except PageFlowError:
                self._apply_fields(qualification)
                stable_since = None
            else:
                now = time.monotonic()
                stable_since = stable_since or now
                if (now - stable_since) * 1000 >= stable_ms:
                    return
            self.page.wait_for_timeout(200)
        raise PageFlowError("OCR稳定等待超时，表单字段无法持续保持与 input.json 一致")

    def submit(self, qualification: Qualification) -> None:
        # 关闭最后一刻出现的 OCR 提示后重新进入稳定校验，不能直接提交。
        self.stabilize_and_verify(qualification, stable_ms=800, max_wait_ms=5_000)
        submit = self.dialog.get_by_text("提交", exact=True)
        if submit.count() != 1:
            raise PageFlowError("资质弹窗找不到唯一“提交”按钮")
        try:
            with self.page.expect_response(
                lambda response: "/permit/web/permit/submitlice" in response.url,
                timeout=self.timeout,
            ) as response_info:
                submit.click(timeout=self.timeout)
            response = response_info.value
            if not response.ok:
                raise PageFlowError(f"资质提交接口 HTTP {response.status}")
            try:
                payload = response.json()
            except Exception as exc:
                raise PageFlowError("资质提交接口返回非 JSON") from exc
            if payload.get("status") != 0:
                raise PageFlowError(
                    f"资质提交失败：{payload.get('message') or payload.get('status')}"
                )
        except PageFlowError:
            raise
        except Exception as exc:
            raise PageFlowError("点击资质“提交”后未收到成功接口响应") from exc
        try:
            if self.inline:
                self.dialog.locator("input").first.wait_for(
                    state="hidden",
                    timeout=self.timeout,
                )
            else:
                self.dialog.wait_for(state="hidden", timeout=self.timeout)
        except Exception as exc:
            form_kind = "内嵌表单未转为资质卡片" if self.inline else "弹窗未关闭"
            raise PageFlowError(f"资质提交成功后{form_kind}") from exc
