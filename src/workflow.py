"""流程 3-6 的接口和页面自动化。"""

from __future__ import annotations

import logging
import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .api_client import BaiduApiClient
from .browser import BrowserSession, is_truth_submit_url
from .errors import (
    AuthenticationRequired,
    PageFlowError,
)
from .industry_qualification import (
    BusinessPanelSnapshot,
    IndustryQualificationPage,
    QualificationCardSnapshot,
    build_execution_plan,
)
from .models import CompanyInput, CompanyRunResult, Qualification, QualificationType
from .qualification_form import (
    QualificationForm,
    qualification_fields_and_file_count_match,
)
from .submission_result import (
    QualificationActionResult,
    SubmissionResult,
)

QUALIFICATION_NODE_XPATH = (
    '//*[@id="app"]/section/section/main/div/div[2]/div/div[2]/div[3]/div[2]/div[1]/div/div[1]/div[1]'
)
LOGGER = logging.getLogger(__name__)


def submit_all_qualifications(page, timeout: int = 30_000) -> None:
    """点击页面级提交按钮，并校验 submitall 接口成功。"""

    button = page.get_by_role(
        "button",
        name=re.compile(r"^(本模块提交|全部提交)$"),
    )
    visible_buttons = [
        button.nth(index)
        for index in range(button.count())
        if button.nth(index).is_visible()
    ]
    if len(visible_buttons) != 1:
        raise PageFlowError(
            f"找不到唯一可见的“本模块提交/全部提交”按钮，匹配数：{len(visible_buttons)}"
        )

    try:
        with page.expect_response(
            lambda response: "/permit/web/permit/submitall" in response.url,
            timeout=timeout,
        ) as response_info:
            visible_buttons[0].click(timeout=timeout)
            confirmation = page.locator(".el-message-box:visible").last
            try:
                confirmation.wait_for(
                    state="visible",
                    timeout=min(timeout, 3_000),
                )
            except Exception:
                confirmation = None
            if confirmation is not None:
                confirmation_text = re.sub(
                    r"\s+",
                    "",
                    confirmation.inner_text(),
                )
                if re.search(r"是否.*提交|确认.*提交|确定.*提交", confirmation_text):
                    confirm = confirmation.get_by_role(
                        "button",
                        name=re.compile(r"确定|确认|提交"),
                    )
                    visible_confirm = [
                        confirm.nth(index)
                        for index in range(confirm.count())
                        if confirm.nth(index).is_visible()
                    ]
                    if not visible_confirm:
                        raise PageFlowError("最终提交确认弹窗中找不到确认按钮")
                    visible_confirm[-1].click(timeout=timeout)
        response = response_info.value
    except PageFlowError:
        raise
    except Exception as exc:
        raise PageFlowError("点击“本模块提交”后未收到 submitall 响应") from exc

    if not response.ok:
        raise PageFlowError(f"全部提交接口 HTTP {response.status}")
    try:
        payload = response.json()
    except Exception as exc:
        raise PageFlowError("全部提交接口返回非 JSON") from exc
    if payload.get("status") != 0:
        raise PageFlowError(
            f"全部提交失败：{payload.get('message') or payload.get('status')}"
        )


@dataclass(frozen=True)
class WorkflowConfig:
    page_timeout_ms: int = 30_000
    max_pages: int = 20
    capture_screenshots: bool = False
    dry_run: bool = False
    final_submit: bool = True


def complete_final_submission(
    page,
    result: SubmissionResult,
    config: WorkflowConfig,
) -> bool:
    """全部单项通过后，根据运行选项决定是否执行页面级最终提交。"""

    if not result.qualifications_success:
        failed_numbers = [
            item.qualification_no
            for item in result.qualifications
            if not item.success
        ]
        raise PageFlowError("存在资质提交失败：" + "、".join(failed_numbers))
    if not config.final_submit:
        LOGGER.info("全部单项资质及最终集合已通过；根据任务选项跳过本模块提交")
        return False
    LOGGER.info("全部单项资质已通过，执行本模块提交")
    submit_all_qualifications(page, timeout=config.page_timeout_ms)
    result.final_submission_success = True
    LOGGER.info("本模块提交成功")
    return True


def _wait_for_exact_text(page, text: str, timeout: int):
    locator = page.get_by_text(text, exact=True).first
    locator.wait_for(state="visible", timeout=timeout)
    return locator


def _click_qualification_node(page, timeout: int) -> None:
    xpath_locator = page.locator(QUALIFICATION_NODE_XPATH)
    if xpath_locator.count() > 0:
        xpath_locator.first.click()
        return
    try:
        _wait_for_exact_text(page, "资质环节", timeout).click()
    except Exception as exc:
        raise PageFlowError("找不到“资质环节”节点") from exc


def enter_qualification_page(page, qualification_url: str, timeout: int) -> str:
    """打开流程页并点击资质环节，返回最终 URL。"""

    page.goto(qualification_url, wait_until="domcontentloaded")
    try:
        _wait_for_exact_text(page, "资质环节", timeout)
    except Exception:
        # 某些页面节点文字在异步渲染后才出现，点击函数会给出最终错误。
        pass
    _click_qualification_node(page, timeout)
    route_error = None
    try:
        page.wait_for_function(
            """() => ['http:', 'https:'].includes(location.protocol) && location.hostname === 'fkzhunru.baidu.com' && location.pathname === '/flice' && location.hash.startsWith('#/truth/submit')""",
            timeout=timeout,
        )
    except Exception as exc:
        route_error = exc
    if route_error is not None or not is_truth_submit_url(page.url):
        try:
            _wait_for_exact_text(page, "URL状态概览", timeout)
        except Exception as exc:
            cause = route_error or exc
            raise PageFlowError(f"点击“资质环节”后未进入真实性资质页面，当前 URL：{page.url}") from cause
    else:
        try:
            _wait_for_exact_text(page, "URL状态概览", timeout)
        except Exception as exc:
            raise PageFlowError(f"真实性资质页面未出现“URL状态概览”，当前 URL：{page.url}") from exc
    return page.url


def _find_url_row(page, target_url: str):
    exact_url = page.get_by_text(target_url, exact=True)
    if exact_url.count():
        url_locator = exact_url.first
        ancestor_candidates = [
            url_locator.locator("xpath=ancestor::tr[1]"),
            url_locator.locator('xpath=ancestor::*[@role="row"][1]'),
            url_locator.locator("xpath=ancestor::*[contains(@class, 'el-table__row')][1]"),
        ]
        for ancestor in ancestor_candidates:
            if ancestor.count():
                return ancestor, exact_url.count()

    candidates = [
        page.locator("tr").filter(has_text=target_url),
        page.locator('[role="row"]').filter(has_text=target_url),
    ]
    for candidate in candidates:
        count = candidate.count()
        if count:
            return candidate, count

    return None, 0


def _click_view_in_row(page, row, timeout: int) -> None:
    candidates = [
        row.get_by_role("button", name="查看"),
        row.get_by_role("link", name="查看"),
        row.get_by_text("查看", exact=True),
    ]
    for candidate in candidates:
        if candidate.count():
            if candidate.count() != 1:
                raise PageFlowError("匹配的 URL 行中存在多个“查看”按钮")
            candidate.click(timeout=timeout)
            return

    # Element UI 的固定操作列可能被渲染到独立 table 中，无法从 URL 所在 tr
    # 向下找到按钮。页面只有一个可见“查看”时可安全点击该按钮。
    global_view = page.get_by_text("查看", exact=True)
    visible_views = [global_view.nth(index) for index in range(global_view.count()) if global_view.nth(index).is_visible()]
    if len(visible_views) == 1:
        visible_views[0].click(timeout=timeout)
        return
    raise PageFlowError(f"匹配的 URL 行中找不到唯一的“查看”按钮，可见按钮数：{len(visible_views)}")


def _click_next_page(page, timeout: int) -> bool:
    selectors = [
        page.locator(".el-pagination .btn-next"),
        page.locator(".ant-pagination-next"),
        page.get_by_role("button", name=re.compile(r"下一页|下页")),
    ]
    for locator in selectors:
        if locator.count() == 0:
            continue
        button = locator.first
        if button.get_attribute("disabled") is not None:
            return False
        class_name = button.get_attribute("class") or ""
        if "disabled" in class_name.casefold():
            return False
        button.click(timeout=timeout)
        return True
    return False


def select_url_and_open_industry_qualification(
    page,
    target_url: str,
    timeout: int,
    max_pages: int = 20,
) -> None:
    """匹配 URL 行，点击该行查看，并等待行业资质区域。"""

    _wait_for_exact_text(page, "URL状态概览", timeout)
    for page_number in range(1, max_pages + 1):
        # “URL状态概览”标题先出现，表格数据随后异步加载。先等待目标 URL
        # 在当前页出现一小段时间，再执行 DOM 行匹配。
        try:
            page.get_by_text(target_url, exact=True).first.wait_for(
                state="visible",
                timeout=min(timeout, 10_000),
            )
        except Exception:
            pass
        row, count = _find_url_row(page, target_url)
        if count > 1:
            raise PageFlowError(f"页面中匹配到多个相同 URL：{target_url}")
        if row is not None:
            _click_view_in_row(page, row, timeout)
            try:
                _wait_for_exact_text(page, "行业资质", timeout)
            except Exception as exc:
                raise PageFlowError("点击“查看”后未出现“行业资质”区域") from exc
            return
        if page_number == max_pages or not _click_next_page(page, timeout):
            break
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
    visible_urls = [
        text.strip()
        for text in page.locator("a[href]").all_inner_texts()
        if text.strip().startswith(("http://", "https://"))
    ]
    raise PageFlowError(f"URL状态概览中找不到目标 URL：{target_url}；页面可见 URL：{visible_urls}")


class WorkflowRunner:
    """串联单个公司流程 3-6。"""

    def __init__(self, session: BrowserSession, config: WorkflowConfig | None = None) -> None:
        self.session = session
        self.config = config or WorkflowConfig()
        if session.context is None:
            raise PageFlowError("WorkflowRunner 需要已启动的浏览器上下文")
        self.api = BaiduApiClient(session.context.request)

    @staticmethod
    def _page_card_for_qualification(
        cards: tuple[QualificationCardSnapshot, ...],
        qualification: Qualification,
    ) -> QualificationCardSnapshot | None:
        matches = [
            item
            for item in cards
            if item.qualification_no == qualification.qualification_no
            and item.qualification_name == qualification.qualification_name
        ]
        if len(matches) > 1:
            raise PageFlowError(
                "页面存在重复“资质编号 + 资质名称”："
                f"{qualification.qualification_no} / {qualification.qualification_name}"
            )
        return matches[0] if matches else None

    @staticmethod
    def _overwrite_card_plan(
        cards: tuple[QualificationCardSnapshot, ...],
    ) -> tuple[
        QualificationCardSnapshot | None,
        tuple[QualificationCardSnapshot, ...],
    ]:
        """生成整类覆盖计划：保留唯一不可删除首卡，其余已填卡全部删除。"""

        unreadable = [
            card
            for card in cards
            if not card.qualification_no and card.qualification_name
        ]
        if unreadable:
            raise PageFlowError("页面存在无法读取资质编号的已填资质卡")

        delete_cards = tuple(
            card
            for card in cards
            if card.qualification_no and card.deletable
        )
        retained_filled = [
            card
            for card in cards
            if card.qualification_no and not card.deletable
        ]
        if len(retained_filled) > 1:
            raise PageFlowError("页面存在多个不可删除的已填资质卡，无法确定首卡")
        if retained_filled:
            return retained_filled[0], delete_cards

        retained_empty = [
            card
            for card in cards
            if not card.qualification_no
            and not card.qualification_name
            and not card.deletable
        ]
        if len(retained_empty) > 1:
            raise PageFlowError("页面存在多个不可删除的空白资质卡，无法确定首卡")
        return (retained_empty[0] if retained_empty else None), delete_cards

    @staticmethod
    def _input_file_hashes(qualification: Qualification) -> tuple[str, ...]:
        hashes: list[str] = []
        for path in qualification.files:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            hashes.append(digest.hexdigest())
        return tuple(hashes)

    def _preflight_existing_qualification_cards(
        self,
        industry: IndustryQualificationPage,
        existing_types: tuple[tuple[QualificationType, BusinessPanelSnapshot], ...],
    ) -> dict[str, tuple[QualificationCardSnapshot, ...]]:
        """在任何修改前验证整类覆盖所需的删除、编辑和新增入口。"""

        snapshots: dict[str, tuple[QualificationCardSnapshot, ...]] = {}
        for qualification_type, panel in existing_types:
            cards = industry.scan_cards(panel)
            try:
                retained_card, delete_cards = self._overwrite_card_plan(cards)
            except PageFlowError as exc:
                raise PageFlowError(
                    f"经营业务“{qualification_type.type_name}”：{exc}"
                ) from exc
            for card in delete_cards:
                LOGGER.info(
                    "流程6预检将删除已有资质：%s / %s",
                    qualification_type.type_name,
                    card.qualification_no,
                )
                industry.validate_card_deletion_target(panel, card)

            qualifications = qualification_type.qualifications
            if qualifications and retained_card is not None:
                LOGGER.info(
                    "流程6预检将用 JSON 第一条覆盖不可删除首卡：%s / %s",
                    qualification_type.type_name,
                    qualifications[0].qualification_no,
                )
                industry.validate_card_edit_target(panel, retained_card)
            new_count = len(qualifications) - (1 if retained_card is not None else 0)
            if new_count > 0:
                industry.validate_backup_upload_target(panel)
            snapshots[qualification_type.type_name] = cards
        return snapshots

    def _recover_form_dialog(self, page) -> None:
        prompt_ok = page.get_by_text("好的", exact=True)
        if prompt_ok.count() and prompt_ok.last.is_visible():
            prompt_ok.last.click(timeout=2_000)
        dialogs = page.locator(".el-dialog:visible")
        if dialogs.count():
            dialog = dialogs.last
            cancel = dialog.get_by_text("取消", exact=True)
            close = dialog.locator(".el-dialog__headerbtn, [aria-label=Close]")
            if cancel.count() and cancel.last.is_visible():
                cancel.last.click(timeout=2_000)
            elif close.count() and close.last.is_visible():
                close.last.click(timeout=2_000)
            else:
                raise PageFlowError("资质处理失败后无法安全关闭表单弹窗")
        page.get_by_text("行业资质", exact=True).first.wait_for(
            state="visible", timeout=self.config.page_timeout_ms
        )

    def _submit_qualification(
        self,
        industry: IndustryQualificationPage,
        panel: BusinessPanelSnapshot,
        qualification: Qualification,
        existing_card: QualificationCardSnapshot | None,
        empty_card: QualificationCardSnapshot | None,
    ) -> tuple[str, tuple[str, ...]]:
        editing = existing_card is not None
        if editing:
            dialog = industry.open_card_editor(panel, existing_card)
            action = "updated"
        else:
            dialog = industry.open_new_qualification(panel, empty_card=empty_card)
            action = "created"
        form = QualificationForm(
            industry.page,
            dialog,
            timeout=self.config.page_timeout_ms,
        )
        if editing:
            form.clear_existing_files(existing_card.file_count)
        uploaded_file_ids = form.upload_files(qualification)
        form.fill_from_input(qualification)
        form.submit(qualification)
        return action, uploaded_file_ids

    def _wait_for_submitted_qualification(
        self,
        industry: IndustryQualificationPage,
        panel: BusinessPanelSnapshot,
        qualification: Qualification,
    ) -> QualificationCardSnapshot:
        """等待异步卡片渲染完成，避免下一条复用尚未更新的备用资质入口。"""

        deadline = time.monotonic() + self.config.page_timeout_ms / 1000
        last_card: QualificationCardSnapshot | None = None
        while time.monotonic() < deadline:
            refreshed_panel = industry.find_business(panel.display_name)
            cards = industry.scan_cards(refreshed_panel)
            last_card = self._page_card_for_qualification(cards, qualification)
            if (
                last_card is not None
                and qualification_fields_and_file_count_match(
                    last_card,
                    qualification,
                )
            ):
                # 再确认一次，防止卡片刚出现但仍处于 OCR/异步刷新过程。
                industry.page.wait_for_timeout(300)
                stable_cards = industry.scan_cards(
                    industry.find_business(panel.display_name)
                )
                stable_card = self._page_card_for_qualification(
                    stable_cards,
                    qualification,
                )
                if (
                    stable_card is not None
                    and qualification_fields_and_file_count_match(
                        stable_card,
                        qualification,
                    )
                ):
                    return stable_card
            industry.page.wait_for_timeout(200)
        if last_card is None:
            raise PageFlowError(
                f"提交后等待资质卡片渲染超时：{qualification.qualification_no} / "
                f"{qualification.qualification_name}"
            )
        raise PageFlowError(
            f"提交后资质卡片字段或文件数量不一致：{qualification.qualification_no} / "
            f"{qualification.qualification_name}"
        )

    def _process_qualification_type(
        self,
        page,
        industry: IndustryQualificationPage,
        qualification_type: QualificationType,
        panel: BusinessPanelSnapshot,
        result: SubmissionResult,
        file_history: dict[
            tuple[str, str, str],
            tuple[tuple[str, ...], tuple[str, ...]],
        ],
        expected_cards: tuple[QualificationCardSnapshot, ...],
    ) -> None:
        panel = industry.find_business(panel.display_name)
        cards = industry.scan_cards(panel)
        expected_signature = sorted(
            (
                item.qualification_no or "",
                item.qualification_name or "",
                item.file_count,
            )
            for item in expected_cards
        )
        current_signature = sorted(
            (
                item.qualification_no or "",
                item.qualification_name or "",
                item.file_count,
            )
            for item in cards
        )
        if current_signature != expected_signature:
            raise PageFlowError(
                f"经营业务“{qualification_type.type_name}”在预检后发生变化，禁止继续修改"
            )
        try:
            _, delete_cards = self._overwrite_card_plan(cards)
        except PageFlowError as exc:
            raise PageFlowError(
                f"经营业务“{qualification_type.type_name}”：{exc}"
            ) from exc
        for card in reversed(delete_cards):
            LOGGER.info(
                "删除已有资质后重新上传：%s / %s",
                qualification_type.type_name,
                card.qualification_no,
            )
            industry.delete_card(panel, card)
            result.deleted_qualifications.append(
                {
                    "typeName": qualification_type.type_name,
                    "qualificationNo": card.qualification_no or "",
                }
            )
            panel = industry.find_business(panel.display_name)

        cards = industry.scan_cards(panel)
        retained_card, remaining_delete_cards = self._overwrite_card_plan(cards)
        if remaining_delete_cards:
            raise PageFlowError(
                f"经营业务“{qualification_type.type_name}”删除已有资质后仍存在可删除卡片"
            )
        for index, qualification in enumerate(qualification_type.qualifications):
            existing = None
            empty_card = None
            if index == 0 and retained_card is not None:
                if retained_card.qualification_no:
                    existing = retained_card
                else:
                    empty_card = retained_card
            current_file_hashes = self._input_file_hashes(qualification)
            try:
                LOGGER.info(
                    "%s资质：%s / %s",
                    "编辑" if existing else "新增",
                    qualification_type.type_name,
                    qualification.qualification_no,
                )
                action, uploaded_file_ids = self._submit_qualification(
                    industry,
                    panel,
                    qualification,
                    existing,
                    empty_card,
                )
                self._wait_for_submitted_qualification(
                    industry,
                    panel,
                    qualification,
                )
                result.qualifications.append(
                    QualificationActionResult(
                        type_name=qualification_type.type_name,
                        qualification_no=qualification.qualification_no,
                        qualification_name=qualification.qualification_name,
                        action=action,
                        success=True,
                        file_count=len(qualification.files),
                        uploaded_file_ids=uploaded_file_ids,
                        input_file_hashes=current_file_hashes,
                    )
                )
                file_history[
                    (
                        qualification_type.type_name,
                        qualification.qualification_no,
                        qualification.qualification_name,
                    )
                ] = (uploaded_file_ids, current_file_hashes)
                retained_card = None
            except Exception as exc:
                LOGGER.error(
                    "资质处理失败：%s / %s / %s：%s",
                    qualification_type.type_name,
                    qualification.qualification_no,
                    qualification.qualification_name,
                    exc,
                )
                result.qualifications.append(
                    QualificationActionResult(
                        type_name=qualification_type.type_name,
                        qualification_no=qualification.qualification_no,
                        qualification_name=qualification.qualification_name,
                        action="updated" if existing else "created",
                        success=False,
                        file_count=len(qualification.files),
                        uploaded_file_ids=(),
                        input_file_hashes=current_file_hashes,
                        error=str(exc),
                    )
                )
                self._recover_form_dialog(page)
                raise PageFlowError(
                    f"资质处理失败：{qualification_type.type_name} / "
                    f"{qualification.qualification_no} / "
                    f"{qualification.qualification_name}：{exc}"
                ) from exc

        final_cards = industry.scan_cards(panel)
        final_keys = Counter(
            (item.qualification_no, item.qualification_name)
            for item in final_cards
            if item.qualification_no
        )
        desired_key_counts = Counter(
            (item.qualification_no, item.qualification_name)
            for item in qualification_type.qualifications
        )
        if final_keys != desired_key_counts:
            raise PageFlowError(
                f"经营业务“{qualification_type.type_name}”资质集合与 input.json 不一致；"
                "页面："
                f"{sorted(final_keys.elements(), key=lambda value: (value[0] or '', value[1] or ''))}；"
                "输入："
                f"{sorted(desired_key_counts.elements(), key=lambda value: (value[0] or '', value[1] or ''))}"
            )

    def _run_industry_qualification(
        self,
        page,
        company: CompanyInput,
    ) -> tuple[bool, bool, str | None]:
        industry = IndustryQualificationPage(page, timeout=self.config.page_timeout_ms)
        panels = industry.scan_businesses()
        plan = build_execution_plan(company, panels)
        file_history = SubmissionResult.load_file_history(company.source_path)
        card_preflight = self._preflight_existing_qualification_cards(
            industry,
            plan.existing_types,
        )
        for panel in plan.delete_businesses:
            LOGGER.info("流程6预检将删除经营业务：%s", panel.display_name)
            industry.validate_business_deletion_target(panel)
        LOGGER.info(
            "流程6预检：%s；已有类型=%d，删除业务=%d，添加类型=%d",
            company.company_name,
            len(plan.existing_types),
            len(plan.delete_businesses),
            len(plan.add_types),
        )

        # 在任何页面修改前，先确认全部缺失类型均能唯一搜索到。
        for _, mapping in plan.add_types:
            LOGGER.info("流程6预检将添加经营业务：%s", mapping.input_name)
            industry.ensure_add_candidate(mapping)
        if plan.add_types:
            industry.validate_add_control()

        if self.config.dry_run:
            LOGGER.info("dry-run 预检通过，不执行页面修改：%s", company.company_name)
            return False, False, None

        result = SubmissionResult(company_name=company.company_name, url=company.url)
        result_path = None
        try:
            for qualification_type, panel in plan.existing_types:
                self._process_qualification_type(
                    page,
                    industry,
                    qualification_type,
                    panel,
                    result,
                    file_history,
                    card_preflight[qualification_type.type_name],
                )

            for panel in reversed(plan.delete_businesses):
                LOGGER.info("删除多余经营业务：%s", panel.display_name)
                industry.delete_business(panel)
                result.deleted_businesses.append(panel.display_name)

            for qualification_type, mapping in plan.add_types:
                LOGGER.info("搜索并添加经营业务：%s", qualification_type.type_name)
                panel = industry.add_business(mapping)
                result.added_businesses.append(panel.display_name)
                new_panel_cards = industry.scan_cards(panel)
                self._process_qualification_type(
                    page,
                    industry,
                    qualification_type,
                    panel,
                    result,
                    file_history,
                    new_panel_cards,
                )

            final_submission_completed = complete_final_submission(
                page,
                result,
                self.config,
            )
            return (
                True,
                final_submission_completed,
                str(company.source_path / "qualification-submit-result.json"),
            )
        except Exception as exc:
            result.error = str(exc)
            raise
        finally:
            result.finish()
            result_path = result.save(company.source_path)

    def run_company(self, company: CompanyInput, workbench_page=None) -> CompanyRunResult:
        LOGGER.info("查询公司并获取资质流程链接")
        cust_id = self.api.search_company(company.company_name)
        qualification_url = self.api.get_qualification_url(cust_id)
        if workbench_page is not None and not workbench_page.is_closed():
            page = workbench_page
        else:
            page = self.session.new_page()
        try:
            LOGGER.info("已获取资质流程链接，开始进入资质页面")
            final_url = enter_qualification_page(
                page,
                qualification_url,
                self.config.page_timeout_ms,
            )
            select_url_and_open_industry_qualification(
                page,
                company.url,
                self.config.page_timeout_ms,
                self.config.max_pages,
            )
            (
                qualification_submission_completed,
                final_submission_completed,
                result_path,
            ) = self._run_industry_qualification(
                page,
                company,
            )
            return CompanyRunResult(
                company_name=company.company_name,
                url=company.url,
                cust_id=cust_id,
                qualification_url=qualification_url,
                final_url=final_url,
                industry_qualification_loaded=True,
                qualification_submission_completed=qualification_submission_completed,
                final_submission_completed=final_submission_completed,
                dry_run=self.config.dry_run,
                submission_result_path=result_path,
            )
        except Exception:
            if self.config.capture_screenshots:
                self.session.save_failure_screenshot(page, company.company_name, "workflow")
            raise

    def run_all(self, companies: tuple[CompanyInput, ...], workbench_page=None) -> tuple[list[CompanyRunResult], list[dict[str, Any]]]:
        successes: list[CompanyRunResult] = []
        failures: list[dict[str, Any]] = []
        for company in companies:
            try:
                successes.append(self.run_company(company, workbench_page=workbench_page))
            except AuthenticationRequired:
                # 登录失效不能被当作普通公司业务错误吞掉，应交回上层登录处理。
                raise
            except Exception as exc:
                failures.append({"companyName": company.company_name, "error": str(exc)})
        return successes, failures
