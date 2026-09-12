"""新版百度资质统一管理中心的业务资质表单操作。"""

from __future__ import annotations

import re
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .errors import PageFlowError
from .card_save import CardSaveObserver, CARD_IDENTITY_JS
from .detail_read_recovery import DetailReadRecovery
from .upload_retry import upload_with_retry
from .upload_identity import (UploadReceipt, preview_files, verify_file_identities,
                              verify_preview_content)

LOGGER = logging.getLogger(__name__)
from .models import CompanyInput, Qualification, QualificationType
from .type_mapping import mapping_for_input, page_name_matches


PERMIT_HOST = "fkzhunru.baidu.com"
SUBMITLICE_PATH = "/permit/web/permit/submitlice"
SAVELICEPIC_PATH = "/permit/web/permit/savelicepic"


def is_permit_post_response(response, expected_path: str) -> bool:
    """仅匹配百度资质域名上指定精确路径的 HTTPS POST 响应。"""

    try:
        parsed = urlsplit(response.url)
        method = response.request.method
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == PERMIT_HOST
        and parsed.path == expected_path
        and method.upper() == "POST"
    )


def evidence_urls_match(actual: str, expected: str) -> bool:
    """比较举证链接；允许仅空片段标记 ``#`` 不同。"""

    actual = actual.strip()
    expected = expected.strip()
    if actual == expected:
        return True
    try:
        actual_url = urlsplit(actual)
        expected_url = urlsplit(expected)
        ports_match = actual_url.port == expected_url.port
    except ValueError:
        return False
    return bool(
        actual_url.scheme
        and expected_url.scheme
        and actual_url.scheme.lower() == expected_url.scheme.lower()
        and actual_url.hostname == expected_url.hostname
        and ports_match
        and actual_url.path == expected_url.path
        and actual_url.query == expected_url.query
        and actual_url.fragment == expected_url.fragment
    )


@dataclass(frozen=True)
class QualificationFile:
    qualification: Qualification
    path: Path


def validate_new_audit_input(company: CompanyInput) -> None:
    promotion = [item for item in company.qualification_types if item.type_name == "推广审查"]
    if len(promotion) != 1:
        raise PageFlowError(
            f"新版业务资质要求输入中恰好存在一个“推广审查”类型，实际：{len(promotion)}"
        )
    for qualification_type in company.qualification_types:
        mapping_for_input(qualification_type.type_name)
        if not qualification_type.qualifications:
            raise PageFlowError(f"资质类型“{qualification_type.type_name}”没有可上传文件")
        for qualification in qualification_type.qualifications:
            if not qualification.files:
                raise PageFlowError(
                    f"资质类型“{qualification_type.type_name}”中的“{qualification.index_name}”没有文件"
                )
            if len(qualification.files) > 9:
                raise PageFlowError(
                    f"资质“{qualification.index_name}”文件数超过9个"
                )


def ordered_new_audit_types(company: CompanyInput) -> tuple[QualificationType, ...]:
    validate_new_audit_input(company)
    promotion = next(
        item for item in company.qualification_types if item.type_name == "推广审查"
    )
    return (promotion,) + tuple(
        item for item in company.qualification_types if item.type_name != "推广审查"
    )


def flatten_qualification_files(
    qualification_type: QualificationType,
) -> tuple[QualificationFile, ...]:
    return tuple(
        QualificationFile(qualification=qualification, path=path)
        for qualification in qualification_type.qualifications
        for path in qualification.files
    )


class NewAuditQualificationPage:
    def __init__(self, page, timeout: int = 30_000) -> None:
        self.page = page
        self.timeout = timeout
        self._scope_sequence = 0
        self._saved_uploads: dict[tuple[int, int], tuple[Path, ...]] = {}
        self._preview_cards: set[tuple[int, int]] = set()
        self._saved_file_receipts: dict[tuple[int, int], tuple[UploadReceipt, ...]] = {}
        self._saved_evidence: dict[tuple[int, int], str] = {}
        self._save_focus_session = None
        self._detail_reads = DetailReadRecovery(page, timeout)

    @staticmethod
    def _visible(locator):
        return [
            locator.nth(index)
            for index in range(locator.count())
            if locator.nth(index).is_visible()
        ]

    def _unique_visible(self, locator, description: str):
        visible = self._visible(locator)
        if len(visible) != 1:
            raise PageFlowError(f"找不到唯一可见的{description}，匹配数：{len(visible)}")
        return visible[0]

    def _wait_for_unique_visible(
        self,
        locator,
        description: str,
        *,
        timeout: int | None = None,
    ):
        self._wait_until(
            lambda: len(self._visible(locator)) == 1,
            f"等待{description}加载超时",
            timeout=timeout,
        )
        return self._unique_visible(locator, description)

    def _add_business_buttons(self):
        return self.page.get_by_role(
            "button",
            name=re.compile(r"^[+＋]?\s*新增业务资质$"),
        )

    def _wait_until(
        self,
        predicate,
        message: str,
        *,
        timeout: int | None = None,
    ) -> None:
        deadline = time.monotonic() + (timeout or self.timeout) / 1000
        while time.monotonic() < deadline:
            self._detail_reads.raise_if_failed()
            try:
                if predicate():
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(100)
        raise PageFlowError(message)

    def _is_new_audit_add_page(self) -> bool:
        try:
            parsed = urlsplit(self.page.url)
        except ValueError:
            return False
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname == PERMIT_HOST
            and parsed.path.rstrip("/") == "/newaudit"
            and parsed.fragment.startswith("/lice/")
            and len(self._visible(self._add_business_buttons())) == 1
        )

    def enter_add_business_page(self, *, allow_resume: bool = True) -> bool:
        if allow_resume and self._open_saved_promotion_for_edit():
            return True
        add = self._wait_for_unique_visible(
            self.page.get_by_role("button", name="新增资质", exact=True),
            "“新增资质”按钮",
            timeout=self.timeout,
        )
        add.click(timeout=self.timeout)
        self._wait_until(
            self._is_new_audit_add_page,
            "点击“新增资质”后未进入新版新增投放资质页面",
        )
        business = self._unique_visible(
            self._add_business_buttons(),
            "“新增业务资质”按钮",
        )
        business.click(timeout=self.timeout)
        self._wait_until(
            lambda: bool(self._business_tabs()),
            "点击“新增业务资质”后未出现业务卡片",
        )
        return False

    def _open_saved_promotion_for_edit(self) -> bool:
        """失败重跑时优先恢复已保存待送审的推广审查草稿。"""

        business_tabs = self.page.get_by_text("已备案业务资质", exact=True)
        try:
            self._wait_until(
                lambda: bool(self._visible(business_tabs)),
                "等待已备案业务资质标签加载超时",
                timeout=self.timeout,
            )
        except PageFlowError:
            self._detail_reads.raise_if_failed()
            return False
        tabs = self._visible(business_tabs)
        if not tabs:
            return False
        tabs[0].click(timeout=self.timeout)
        # Element Plus 切换标签时会短暂渲染“0个业务资质”，随后再填充
        # 服务端记录；先让这一过渡帧结束，避免误判为没有可恢复草稿。
        self.page.wait_for_timeout(1_000)

        def matching_rows() -> list[object]:
            matches: list[object] = []
            for row in self._visible(self.page.locator("tr")):
                if (
                    row.get_by_text("推广审查", exact=True).count()
                    and row.get_by_text("已保存待送审", exact=True).count()
                    and row.get_by_role("button", name="修改", exact=True).count()
                ):
                    matches.append(row)
            return matches

        zero_since: float | None = None

        def list_settled() -> bool:
            nonlocal zero_since
            if self._detail_reads.pending or time.monotonic() - self._detail_reads.last_finished < 0.3:
                zero_since = None
                return False
            if matching_rows():
                return True
            zero_visible = bool(
                self._visible(
                    self.page.get_by_text(
                        re.compile(r"共\s*0\s*个业务资质"),
                    )
                )
            )
            if not zero_visible:
                zero_since = None
                return False
            if zero_since is None:
                zero_since = time.monotonic()
            return time.monotonic() - zero_since >= 3.0

        try:
            self._wait_until(
                list_settled,
                "等待已备案业务资质列表加载超时",
                timeout=self.timeout,
            )
        except PageFlowError as exc:
            raise PageFlowError(f'已备案业务资质列表读取未完成，不能将暂时空列表作为新增依据：{exc}') from exc
        rows = matching_rows()
        if len(rows) > 1:
            raise PageFlowError("存在多个已保存待送审的推广审查，无法安全恢复")
        if not rows:
            return False
        edit = self._unique_visible(
            rows[0].get_by_role("button", name="修改", exact=True),
            "推广审查“修改”按钮",
        )
        edit.click(timeout=self.timeout)
        self._wait_until(
            lambda: (
                urlsplit(self.page.url).hostname == PERMIT_HOST
                and bool(
                    self._visible(
                        self.page.get_by_text("编辑投放资质", exact=True)
                    )
                )
                and self.page.locator('input[type="file"]').count() > 0
                and bool(
                    self._visible(
                        self.page.get_by_role("button", name="取消", exact=True)
                    )
                )
            ),
            "点击推广审查“修改”后未进入编辑页",
        )
        return True

    def _business_tabs(self) -> dict[int, object]:
        tabs = self.page.get_by_text(re.compile(r"^业务\d+$"), exact=True)
        result: dict[int, object] = {}
        # 一次快照只提取名称，不保存全局正则的 nth 位置。
        # 切换业务时同名卡片标题会增减，导致旧 nth 消失或指向另一业务。
        names = tabs.and_(self.page.locator(":visible")).all_text_contents()
        for name in names:
            match = re.fullmatch(r"业务(\d+)", name.strip())
            if match:
                # 同一文案可能同时出现在顶部标签和当前卡片标题；DOM 中
                # 顶部标签在前；每次使用时重新匹配此业务的首个可见项。
                index = int(match.group(1))
                result.setdefault(index, self.page.get_by_text(
                    f"业务{index}", exact=True,
                ).and_(self.page.locator(":visible")).first)
        return result

    def _click_business_tab(self, index: int) -> None:
        LOGGER.info("业务[%s]：切换并等待业务表单", index)
        tabs = self._business_tabs()
        if index not in tabs:
            raise PageFlowError(f"找不到业务{index}标签")
        try:
            tabs[index].click(timeout=self.timeout)
        except PlaywrightTimeoutError:
            raise PageFlowError(f'业务{index}标签未出现或不可点击，停止，不切换其他业务') from None
        self._wait_until(
            lambda: self._business_container(index) is not None,
            f"业务{index}卡片未显示",
        )

    def _business_container(self, index: int):
        """定位业务内容卡片，排除顶部同名标签和其他业务的表单。"""

        # 真实新版 DOM：每项业务单独放在 business-form-card 内。
        # 先按精确业务标题限定卡片，避免遍历到含全部业务的页面根节点。
        cards = self._visible(self.page.locator('.business-form-card').filter(
            has=self.page.get_by_text(f"业务{index}", exact=True),
        ))
        if len(cards) > 1:
            raise PageFlowError(f"业务{index}存在多个内容卡片，停止操作")
        if cards:
            return cards[0]

        labels = self._visible(
            self.page.get_by_text(f"业务{index}", exact=True)
        )
        candidates: dict[str, tuple[int, int, bool, bool, bool, object]] = {}
        for label in labels:
            ancestors = label.locator(
                "xpath=ancestor-or-self::*["
                ".//input[@type='file'] or "
                ".//input[contains(@placeholder,'经营') or "
                "contains(@placeholder,'类目') or @role='combobox']"
                "]"
            )
            for candidate in self._visible(ancestors):
                token = candidate.get_attribute("data-bpf-business-scope")
                if not token:
                    self._scope_sequence += 1
                    token = f"scope-{self._scope_sequence}"
                    candidate.evaluate(
                        "(element, value) => element.setAttribute('data-bpf-business-scope', value)",
                        token,
                    )
                has_supplement = bool(
                    candidate.get_by_text(
                        "我还需要补充其他资质",
                        exact=True,
                    ).count()
                    or candidate.get_by_text("新增补充资质", exact=True).count()
                )
                has_query = bool(
                    candidate.locator(
                        "input[placeholder*='经营'], input[placeholder*='类目'], "
                        "input[role='combobox']"
                    ).count()
                )
                has_file = bool(candidate.locator('input[type="file"]').count())
                candidates[token] = (
                    candidate.get_by_text(
                        re.compile(r"^业务\d+$"),
                        exact=True,
                    ).count(),
                    candidate.locator("*").count(),
                    has_supplement,
                    has_query,
                    has_file,
                    candidate,
                )
        if not candidates:
            return None
        pool = list(candidates.values())
        minimum_business_labels = min(item[0] for item in pool)
        pool = [item for item in pool if item[0] == minimum_business_labels]
        if any(has_query for _, _, _, has_query, _, _ in pool):
            pool = [item for item in pool if item[3]]
        elif any(has_supplement for _, _, has_supplement, _, _, _ in pool):
            pool = [item for item in pool if item[2]]
        else:
            pool = [item for item in pool if item[4]]
        smallest = min(size for _, size, *_ in pool)
        matches = [
            candidate
            for _, size, *_, candidate in pool
            if size == smallest
        ]
        if len(matches) != 1:
            raise PageFlowError(
                f"业务{index}内容容器无法唯一定位，最小候选数：{len(matches)}"
            )
        return matches[0]

    def _close_business_tab(self, index: int) -> None:
        LOGGER.info("默认业务[%s]：删除业务并核对剩余数量", index)
        tab = self._business_tabs().get(index)
        if tab is None:
            raise PageFlowError(f"删除前找不到业务{index}")
        before = len(self._business_tabs())
        card = self._business_container(index)
        if card is not None:
            card_deletes = self._visible(
                card.get_by_role("button", name="删除", exact=True)
            )
            if len(card_deletes) > 1:
                raise PageFlowError(f"业务{index}卡片存在多个删除按钮，停止操作")
            if card_deletes:
                card_deletes[0].click(timeout=self.timeout)
                self._wait_until(
                    lambda: len(self._business_tabs()) == before - 1,
                    f"删除业务{index}后业务数量未减少",
                )
                return
        container = tab.locator(
            "xpath=ancestor-or-self::*[contains(@class,'tab') or contains(@class,'tag')][1]"
        )
        if not container.count():
            container = tab.locator("xpath=..")
        controls = [
            container.get_by_role("button", name=re.compile(r"关闭|删除")),
            container.locator("[class*='close'], .el-icon-close"),
        ]
        for control in controls:
            visible = self._visible(control)
            if visible:
                visible[-1].click(timeout=self.timeout)
                self._wait_until(
                    lambda: len(self._business_tabs()) == before - 1,
                    f"删除业务{index}后业务数量未减少",
                )
                return
        raise PageFlowError(f"业务{index}标签找不到删除入口")

    def _business_indices_matching(self, input_name: str) -> list[int]:
        matches: list[int] = []
        for index in sorted(self._business_tabs()):
            self._click_business_tab(index)
            container = self._business_container(index)
            if container is not None and self._business_type_matches(container, input_name):
                matches.append(index)
        return matches

    def remove_default_extra_businesses(self) -> int:
        tabs = self._business_tabs()
        if not tabs:
            raise PageFlowError("新版新增页没有可清理的默认业务")
        promotion_indices = self._business_indices_matching("推广审查")
        if len(promotion_indices) != 1:
            raise PageFlowError(
                "默认业务中找不到唯一“推广审查”，"
                f"匹配数：{len(promotion_indices)}"
            )
        promotion_index = promotion_indices[0]
        for index in sorted((set(tabs) - {promotion_index}), reverse=True):
            self._close_business_tab(index)
        remaining = self._business_tabs()
        if len(remaining) != 1:
            raise PageFlowError("默认业务清理后未只保留唯一推广审查")
        final_indices = self._business_indices_matching("推广审查")
        if len(final_indices) != 1:
            raise PageFlowError("默认业务清理后剩余业务不是唯一推广审查")
        return final_indices[0]

    def remove_all_default_businesses(self) -> None:
        """推广审查已单独保存时，清空新增页自动带出的其他默认业务。"""

        for index in sorted(self._business_tabs(), reverse=True):
            self._close_business_tab(index)
        if self._business_tabs():
            raise PageFlowError("默认业务清理后仍有残留业务")

    def prepare_promotion_business(
        self,
        qualification_type: QualificationType,
    ) -> int:
        promotion_indices = self._business_indices_matching("推广审查")
        if len(promotion_indices) > 1:
            raise PageFlowError(
                f"默认业务中存在多个“推广审查”，匹配数：{len(promotion_indices)}"
            )
        if not promotion_indices:
            self.add_business(qualification_type)
        return self.remove_default_extra_businesses()

    def _business_type_matches(self, container, input_name: str) -> bool:
        mapping = mapping_for_input(input_name)
        values: list[str] = []
        query_inputs = self._visible(
            self._business_query_inputs(container)
        )
        values.extend(item.input_value().strip() for item in query_inputs)

        labels = self._visible(container.get_by_text("经营业务", exact=True))
        for label in labels:
            field = label.locator(
                "xpath=ancestor::*[self::label or "
                "contains(@class,'form-item') or contains(@class,'field') or "
                "contains(@class,'row')][1]"
            )
            if not field.count():
                field = label.locator("xpath=..")
            text = field.inner_text()
            label_text = label.inner_text()
            if label_text in text:
                text = text.replace(label_text, "", 1)
            text = re.sub(r"^[*＊：:\s]+", "", text).strip()
            if text:
                values.append(text)
        return any(page_name_matches(mapping, value) for value in values)

    @staticmethod
    def _business_query_inputs(container):
        return container.locator(
            "input[placeholder*='经营'], input[placeholder*='类目'], "
            "input[role='combobox']"
        )

    def add_business(self, qualification_type: QualificationType) -> int:
        before = set(self._business_tabs())
        add = self._unique_visible(
            self._add_business_buttons(),
            "“新增业务资质”按钮",
        )
        add.click(timeout=self.timeout)
        last_indices, stable_since = None, None

        def added_and_stable():
            nonlocal last_indices, stable_since
            current = set(self._business_tabs())
            if not before.issubset(current) or not current - before:
                return False
            if current != last_indices:
                last_indices, stable_since = current, time.monotonic()
                return False
            return time.monotonic() - stable_since >= 0.5

        self._wait_until(
            added_and_stable,
            f"新增经营业务“{qualification_type.type_name}”后未出现新业务卡片",
        )
        added = set(self._business_tabs()) - before
        LOGGER.info('业务[%s]：新增前 %s 张，本次出现 %s 张新卡片', qualification_type.type_name, len(before), len(added))
        if len(added) != 1:
            if before:
                raise PageFlowError('已有业务时出现多张新业务卡片，停止，不修改原业务')
            return self._select_from_empty_default_businesses(qualification_type.type_name)
        index = next(iter(added))
        self._click_business_tab(index)
        self._select_business_type(index, qualification_type.type_name)
        return index

    def _select_from_empty_default_businesses(self, input_name: str) -> int:
        """零业务起点重建了默认卡片；仅复用已确认全空的目标卡。"""
        editable = []
        for index in sorted(self._business_tabs()):
            self._click_business_tab(index)
            card = self._business_container(index)
            if not self._file_inputs_in(card):
                raise PageFlowError('默认业务上传表单未加载，无法确认空白状态')
            for file_input in self._file_inputs_in(card):
                form = self._upload_container(file_input)
                fields = self._visible(form.locator('input:not([type="file"]):not([role="combobox"])'))
                counts = form.locator('.file-count').all_inner_texts()
                if (preview_files(form) or any(f.input_value().strip() for f in fields)
                        or any(re.match(r'\s*[1-9]\d*\s*/', text) for text in counts)
                        or self._visible(form.get_by_text('已保存待送审', exact=True))):
                    raise PageFlowError('重新生成的默认业务卡片不是空白，停止，不清理已有资料')
            inputs = self._visible(self._business_query_inputs(card))
            if inputs and inputs[-1].is_editable():
                editable.append(index)
        matches = self._business_indices_matching(input_name)
        if len(matches) > 1:
            raise PageFlowError('默认业务中目标类型不唯一，停止，不删除业务')
        if not matches:
            if not editable:
                # 空页的第一次新增只恢复固定类型默认组；保留该组再次
                # 点击新增，页面才产生可选择经营业务的独立空白卡。
                self.add_business(QualificationType(input_name, ()))
            else:
                self._click_business_tab(editable[0])
                self._select_business_type(editable[0], input_name)
        while True:
            matches = self._business_indices_matching(input_name)
            if len(matches) != 1:
                raise PageFlowError('清理默认业务时目标类型不唯一，停止')
            others = set(self._business_tabs()) - {matches[0]}
            if not others:
                return matches[0]
            self._click_business_tab(max(others))
            self._close_business_tab(max(others))

    def _select_business_type(self, business_index: int, input_name: str) -> None:
        mapping = mapping_for_input(input_name)
        container = self._business_container(business_index)
        if container is None:
            raise PageFlowError(f"业务{business_index}内容容器不存在")
        inputs = self._business_query_inputs(container)
        visible_inputs = self._visible(inputs)
        if not visible_inputs:
            raise PageFlowError("新增业务卡片找不到“经营业务”查询输入框")
        search = visible_inputs[-1]
        search.fill(input_name)

        def exact_candidates() -> list[object]:
            candidates: list[object] = []
            for alias in mapping.page_names:
                candidates.extend(
                    self._visible(
                        self.page.get_by_role("option", name=alias, exact=True)
                    )
                )
            if candidates:
                return candidates
            dropdowns = self._visible(
                self.page.locator(".el-select-dropdown, [role='listbox']")
            )
            for dropdown in dropdowns:
                for alias in mapping.page_names:
                    candidates.extend(
                        self._visible(dropdown.get_by_text(alias, exact=True))
                    )
            return candidates

        self._wait_until(
            lambda: bool(exact_candidates()),
            f"经营业务“{input_name}”查询后未出现精确候选项",
        )
        candidates = exact_candidates()
        if len(candidates) != 1:
            raise PageFlowError(
                f"经营业务“{input_name}”没有唯一精确候选项，匹配数：{len(candidates)}"
            )
        if not candidates[0].is_enabled():
            raise PageFlowError(
                f"经营业务“{input_name}”的精确候选项被百度禁用，"
                "无法选择；请人工确认该公司适用的资质流程"
            )
        candidates[0].click(timeout=self.timeout)

        def selected_value_matches() -> bool:
            current = self._business_container(business_index)
            if current is None:
                return False
            selected_inputs = self._visible(
                self._business_query_inputs(current)
            )
            if selected_inputs and page_name_matches(
                mapping,
                selected_inputs[-1].input_value(),
            ):
                return True
            return any(
                self._visible(current.get_by_text(alias, exact=True))
                for alias in mapping.page_names
            )

        self._wait_until(
            selected_value_matches,
            f"选择经营业务“{input_name}”后页面未回显",
        )

    @staticmethod
    def _submitlice_response(response, filename: str) -> None:
        if response.status != 200:
            raise PageFlowError(f"资质自动保存接口 HTTP {response.status}：{filename}")
        try:
            payload = response.json()
        except Exception as exc:
            raise PageFlowError("资质自动保存接口返回非 JSON") from exc
        if not isinstance(payload, dict):
            raise PageFlowError("资质自动保存接口响应结构异常")
        if payload.get("status") != 0:
            raise PageFlowError(
                f"资质自动保存失败：{payload.get('message') or payload.get('status')}"
            )

    def _file_inputs(self, business_index: int):
        container = self._business_container(business_index)
        if container is None:
            raise PageFlowError(f"业务{business_index}内容容器不存在")
        return self._file_inputs_in(container)

    @staticmethod
    def _file_inputs_in(container):
        # Element UI 会隐藏原生 file input；set_input_files 支持直接操作隐藏控件。
        inputs = container.locator('input[type="file"]')
        result = []
        for index in range(inputs.count()):
            file_input = inputs.nth(index)
            form_card = file_input.locator(
                "xpath=ancestor::div["
                "contains(concat(' ', normalize-space(@class), ' '), ' form-card ')"
                "][1]"
            )
            # input 本身由 Element UI 隐藏；应判断承载它的卡片是否可见。
            if form_card.count() and not form_card.is_visible():
                continue
            result.append(file_input)
        return result

    @staticmethod
    def _is_supplement_input(file_input) -> bool:
        return bool(
            file_input.locator(
                "xpath=ancestor::*["
                "contains(concat(' ', normalize-space(@class), ' '), "
                "' add-reserve ')][1]"
            ).count()
        )

    def _wait_for_initial_main_form_count(self, container_getter) -> int:
        """等待业务配置异步渲染完全部内置必填资质卡。"""

        stable_count = 0
        stable_since: float | None = None

        def settled() -> bool:
            nonlocal stable_count, stable_since
            main_count = sum(
                not self._is_supplement_input(file_input)
                for file_input in self._file_inputs_in(container_getter())
            )
            if main_count <= 0:
                stable_count = 0
                stable_since = None
                return False
            if main_count != stable_count:
                stable_count = main_count
                stable_since = time.monotonic()
                return False
            return bool(
                stable_since is not None
                and time.monotonic() - stable_since >= 0.5
            )

        self._wait_until(settled, "等待业务自带的主资质表单加载超时")
        return stable_count

    def _ensure_upload_form_count(self, business_index: int, expected: int) -> None:
        self._ensure_upload_form_count_in(
            lambda: self._business_container(business_index), expected
        )

    def _ensure_upload_form_count_in(self, container_getter, expected: int) -> None:
        while len(self._file_inputs_in(container_getter())) < expected:
            LOGGER.info("资质卡片：新增补充表单，目标数量 %s", expected)
            container = container_getter()
            inputs = self._file_inputs_in(container)
            before = len(inputs)
            if before == 0:
                # 经营业务选中后，百度会异步请求并渲染该业务的必填
                # 资质配置。加载窗口内不能误点补充资质入口。
                self._wait_until(
                    lambda: len(self._file_inputs_in(container_getter())) >= 1,
                    "等待业务自带的主资质表单加载超时",
                )
                continue
            supplement_count = sum(
                self._is_supplement_input(file_input) for file_input in inputs
            )
            if supplement_count == 0:
                checkbox_text = self._unique_visible(
                    container.get_by_text("我还需要补充其他资质", exact=True),
                    "“我还需要补充其他资质”选项",
                )
                checkbox_text.click(timeout=self.timeout)
            else:
                add_candidates = self._visible(
                    container.get_by_text("新增补充资质", exact=True)
                )
                if not add_candidates:
                    # 补充资质保存后父组件会刷新列表；真实页面偶发把
                    # needReserveLice 恢复为 false，但已保存卡片仍保留。
                    # 此时只恢复未勾选的开关，不触碰已有资质数据。
                    checkbox_text = self._unique_visible(
                        container.get_by_text(
                            "我还需要补充其他资质", exact=True
                        ),
                        "“我还需要补充其他资质”选项",
                    )
                    checkbox = checkbox_text.locator(
                        "xpath=ancestor-or-self::label[1]//input[@type='checkbox']"
                    )
                    if checkbox.count() != 1 or checkbox.is_checked():
                        raise PageFlowError(
                            "已有补充资质但“新增补充资质”入口不可见"
                        )
                    checkbox_text.click(timeout=self.timeout)
                    self._wait_until(
                        lambda: len(
                            self._visible(
                                container_getter().get_by_text(
                                    "新增补充资质", exact=True
                                )
                            )
                        )
                        == 1,
                        "恢复补充资质开关后入口仍不可见",
                    )
                    container = container_getter()
                    add_candidates = self._visible(
                        container.get_by_text("新增补充资质", exact=True)
                    )
                if len(add_candidates) != 1:
                    raise PageFlowError(
                        "找不到唯一可见的“新增补充资质”入口，"
                        f"匹配数：{len(add_candidates)}"
                    )
                add = add_candidates[0]
                add.click(timeout=self.timeout)
            self._wait_until(
                lambda: len(self._file_inputs_in(container_getter())) == before + 1,
                f"未能创建第{before}个补充资质表单",
            )

    def _discard_empty_initial_supplements(self, container_getter) -> None:
        """清除新增页偶发恢复的空补充卡；有任何数据时立即停止。"""

        container = container_getter()
        inputs = self._file_inputs_in(container)
        supplement_inputs = [
            file_input
            for file_input in inputs
            if self._is_supplement_input(file_input)
        ]
        if not supplement_inputs:
            return
        for file_input in supplement_inputs:
            card = self._upload_container(file_input)
            evidence_inputs = self._visible(card.locator('input:not([type="file"])'))
            preview_counts = [
                "".join(item.inner_text().split())
                for item in self._visible(card.locator(".file-count"))
            ]
            has_files = bool(
                card.locator(".delete-btn").count()
                or any(
                    re.fullmatch(r"[1-9]\d*/\d+", count)
                    for count in preview_counts
                )
            )
            has_saved_status = bool(
                self._visible(card.get_by_text("已保存待送审", exact=True))
            )
            has_evidence = any(item.input_value().strip() for item in evidence_inputs)
            if has_files or has_saved_status or has_evidence:
                raise PageFlowError("新增页存在非空补充资质草稿，拒绝自动覆盖")

        checkbox = self._unique_visible(
            container.get_by_text("我还需要补充其他资质", exact=True),
            "“我还需要补充其他资质”选项",
        )
        checkbox.click(timeout=self.timeout)
        main_count = len(inputs) - len(supplement_inputs)
        self._wait_until(
            lambda: len(self._file_inputs_in(container_getter())) == main_count,
            "清理空补充资质卡片后页面未恢复为内置卡数量",
        )

    def _upload_container(self, file_input):
        # 新版真实页面把自动保存的 mouseleave 绑定在外层
        # ``div.form-card``，而不是内部 ``form.lice-form``。优先返回
        # 这个精确边界；旧夹具/兼容页面没有该类时再退回语义祖先。
        form_card = file_input.locator(
            "xpath=ancestor::div["
            "contains(concat(' ', normalize-space(@class), ' '), ' form-card ')"
            "][1]"
        )
        if form_card.count():
            return form_card
        container = file_input.locator(
            "xpath=ancestor::*[.//*[normalize-space(.)='举证链接']][1]"
        )
        if not container.count():
            raise PageFlowError("上传控件找不到对应举证链接区域")
        return container

    def _scroll_upload_to_bottom(self, card) -> None:
        """滚动页面及卡片的可滚动祖先到底部，再保证当前卡片可操作。"""
        card.evaluate("""element => {
          for (let p = element.parentElement; p; p = p.parentElement) {
            if (p.scrollHeight > p.clientHeight &&
                /auto|scroll/.test(getComputedStyle(p).overflowY))
              p.scrollTop = p.scrollHeight;
          }
          const root = document.scrollingElement;
          if (root) root.scrollTop = root.scrollHeight;
        }""")

    def _invoke_card_save(self, card):
        """调用当前卡片组件显式暴露的 handleSubmit，不调用父页面提交。"""
        handle = card.element_handle(timeout=self.timeout)
        if handle is None:
            raise PageFlowError('当前资质卡片已消失，未调用保存方法')
        started = handle.evaluate("""element => {
          const candidates = new Set();
          const consider = c => {
            const root = c?.subTree?.el;
            const ownsCard = root === element || (
              root?.classList?.contains('drag-upload-wrapper') &&
              root.querySelectorAll('.form-card').length === 1 &&
              root.querySelector('.form-card') === element
            );
            if (ownsCard && typeof c.exposed?.handleSubmit === 'function')
              candidates.add(c.exposed);
          };
          // 开发模式可从DOM找到组件；生产构建只保留应用根节点的VNode树。
          for (let c = element.__vueParentComponent; c; c = c.parent) consider(c);
          let appRoot = element;
          while (appRoot && !appRoot._vnode) appRoot = appRoot.parentElement;
          const seen = new Set();
          const walk = v => {
            if (!v || typeof v !== 'object' || seen.has(v)) return;
            seen.add(v);
            if (v.component) { consider(v.component); walk(v.component.subTree); }
            if (Array.isArray(v.children)) v.children.forEach(walk);
            if (v.suspense) walk(v.suspense.activeBranch);
          };
          walk(appRoot?._vnode);
          if (candidates.size !== 1) return false;
          const api = [...candidates][0];
          element.__bpfSaveFailed = false;
          try {
            Promise.resolve(api.handleSubmit()).catch(() => { element.__bpfSaveFailed = true; });
          } catch (_) { element.__bpfSaveFailed = true; }
          return true;
        }""")
        if not started:
            handle.dispose()
            raise PageFlowError('找不到当前资质卡片唯一的页面保存方法 handleSubmit，未调用其他提交入口')
        return handle

    def _save_qualification_card(self, card_getter, container_getter, evidence, receipts, name,
                                 *, save_scope=None):
        if save_scope is None:
            with CardSaveObserver(self.page) as observer:
                scope = (observer, observer.checkpoint(), card_getter().evaluate(CARD_IDENTITY_JS))
                return self._save_observed_card(card_getter, evidence, receipts, name, scope)
        return self._save_observed_card(card_getter, evidence, receipts, name, save_scope)

    def _save_observed_card(self, card_getter, evidence, receipts, name, scope, *, allow_trigger=True):
        observer, cursor, identity = scope
        save_handle = None
        try:
            if allow_trigger:
                card = card_getter()
                self._scroll_upload_to_bottom(card)
                field = self._unique_visible(card.locator('input:not([type="file"])'),
                                             f'资质[{name}]的举证链接输入框')
                if field.input_value().strip() != evidence:
                    field.click(timeout=self.timeout)
                    field.fill(evidence)
                card_getter().hover(timeout=self.timeout)
            deadline = time.monotonic() + self.timeout / 1000
            # 填写和鼠标动作也可能保存，动作后再次检查全程观察结果。
            state = 'absent'
            while time.monotonic() < deadline:
                state, event = observer.state(cursor, identity, receipts, evidence)
                if state == 'saved':
                    LOGGER.info('资质[%s]：保存接口成功（HTTP 200，status=0），开始核对页面回填', name)
                    return event.response
                if state == 'unknown':
                    if observer.readback(cursor, identity, receipts, evidence, self.timeout):
                        LOGGER.info('资质[%s]：保存响应未知，已通过详情接口核对持久化文件与举证', name)
                        return None
                    raise PageFlowError(f'资质[{name}]保存结果未知，详情核对未确认，未重复上传或保存')
                if state in ('absent', 'different') and save_handle is None:
                    if not allow_trigger:
                        raise PageFlowError(f'资质[{name}]核验期间保存状态发生变化，未上传下一个文件')
                    LOGGER.info('资质[%s]：调用当前卡片 handleSubmit 保存', name)
                    save_handle = self._invoke_card_save(card_getter())
                if save_handle is not None and save_handle.evaluate('element => element.__bpfSaveFailed === true'):
                    raise PageFlowError(f'资质[{name}]页面保存方法执行失败，未上传下一个文件')
                self.page.wait_for_timeout(100)
            if state == 'pending':
                raise PageFlowError(f'资质[{name}]已发出保存请求，但请求仍未结束，未重复提交')
            if observer.related(cursor, identity, receipts):
                raise PageFlowError(f'资质[{name}]保存请求的卡片、文件或举证与预期不一致，未上传下一个文件')
            raise PageFlowError(f'资质[{name}]已调用页面保存方法，但未发出保存请求，请检查页面校验提示')
        finally:
            if save_handle is not None:
                save_handle.dispose()

    def _click_outside_qualification_card(self) -> None:
        for locator in (
            self.page.get_by_text("URL信息", exact=True),
            self.page.get_by_text("信息资质管理", exact=True),
        ):
            visible = self._visible(locator)
            if visible:
                visible[0].click(timeout=self.timeout)
                return
        raise PageFlowError("找不到资质卡片外的稳定区域以触发自动保存")

    def _click_blank_outside_card(self, card, business_container) -> None:
        """点击业务卡内、资质卡外的非交互空白区域。"""

        self.page.bring_to_front()
        # Chromium 的 bring_to_front 只切换标签；桌面应用在前台时，
        # document.hasFocus() 仍可能为 false，使站点的 mouseleave 保存失效。
        # 仅为 worker 的独立页面启用焦点模拟，随浏览器上下文关闭而释放。
        if not self.page.evaluate("document.hasFocus()"):
            try:
                if self._save_focus_session is None:
                    self._save_focus_session = self.page.context.new_cdp_session(self.page)
                self._save_focus_session.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            except Exception:
                raise PageFlowError("无法取得资质页面焦点，未触发自动保存") from None
            if not self.page.evaluate("document.hasFocus()"):
                raise PageFlowError("资质页面仍无焦点，未触发自动保存")
        card.hover(timeout=self.timeout)
        card_box = card.bounding_box()
        business_box = business_container.bounding_box()
        if not card_box or not business_box:
            raise PageFlowError("无法计算资质卡片外的安全空白区域")
        viewport = self.page.evaluate('({width: innerWidth, height: innerHeight})')
        visible_y = max(12, min(viewport['height'] - 12,
                               card_box['y'] + card_box['height'] / 2))
        candidates = (
            (min(viewport['width'] - 12, business_box['x'] + business_box['width'] - 12), visible_y),
            (max(12, business_box['x'] + 12), visible_y),
            (
                business_box["x"] + business_box["width"] - 12,
                card_box["y"] + min(30, card_box["height"] / 2),
            ),
            (
                business_box["x"] + business_box["width"] - 12,
                business_box["y"] + business_box["height"] / 2,
            ),
            (
                business_box["x"] + 12,
                business_box["y"] + business_box["height"] - 12,
            ),
        )
        for x, y in candidates:
            outside = not (
                card_box["x"] <= x <= card_box["x"] + card_box["width"]
                and card_box["y"] <= y <= card_box["y"] + card_box["height"]
            )
            if not outside:
                continue
            safe = self.page.evaluate(
                """({x, y}) => {
                  const element = document.elementFromPoint(x, y);
                  return x >= 0 && y >= 0 && x < innerWidth && y < innerHeight
                    && !!element && !element.closest(
                    'a,button,input,textarea,select,[role="button"],[role="checkbox"]'
                  );
                }""",
                {"x": x, "y": y},
            )
            if safe:
                self.page.mouse.click(x, y)
                return
        raise PageFlowError("找不到资质卡片外可点击的安全空白处")

    def _wait_for_uploaded_file_state(
        self,
        card,
        expected_count: int,
        qualification_name: str,
    ) -> None:
        """等待上传组件完成 success 回调并把服务端文件回填到表单。"""

        preview = card.locator(".preview-container")
        if preview.count():
            count_pattern = re.compile(rf"^{expected_count}/\d+$")

            def preview_ready() -> bool:
                return any(
                    count_pattern.fullmatch("".join(item.inner_text().split()))
                    for item in self._visible(preview.locator(".file-count"))
                )

            self._wait_until(
                preview_ready,
                f"等待资质“{qualification_name}”上传组件回填{expected_count}个文件超时",
            )
            return

        # 兼容页面没有百度预览组件时，仅核对本次选择；累计数量不能
        # 从 input.files 推断（逐张上传后它仅包含最后一张）。
        file_input = card.locator('input[type="file"]').first
        self._wait_until(
            lambda: file_input.evaluate("element => element.files.length") == 1,
            f"等待资质“{qualification_name}”文件选择状态超时",
        )

    def _verify_saved_file_count(self, card, expected_count: int, name: str,
                                 *, required: bool = False) -> None:
        """保存刷新后重新读取预览；本地兼容页面无预览时使用已有保存凭据。"""
        if not required and not card.locator(".preview-container").count():
            return
        try:
            self._wait_until(lambda: card.locator(".preview-container").count() > 0,
                             "等待保存后的文件预览区域超时")
            self._wait_for_uploaded_file_state(card, expected_count, name)
        except PageFlowError as exc:
            raise PageFlowError(
                f"资质“{name}”保存后页面文件不完整或未显示，期望 {expected_count} 个，"
                "停止，不重复上传或发起审核"
            ) from exc

    def _verify_file_receipts(self, card_getter, receipts, name, *, content=False):
        verify_file_identities(receipts, [r.server_id for r in receipts], description=name)
        stable_since = None

        def ready():
            nonlocal stable_since
            files = preview_files(card_getter())
            try:
                verify_file_identities(receipts, [item['id'] for item in files], description=name)
                matches = all(item['ready'] for item in files)
            except PageFlowError:
                matches = False
            if not matches:
                stable_since = None
                return False
            if stable_since is None:
                stable_since = time.monotonic()
            # 给异步 change/success/父组件回填留出稳定时间；也避免同秒紧邻上传。
            return time.monotonic() - stable_since >= 1.1

        self._wait_until(ready, f'资质“{name}”文件身份或图片加载不一致，停止，不重复上传')
        if content:
            verify_preview_content(self.page, receipts, preview_files(card_getter()), self.timeout)
            verify_file_identities(receipts, [item['id'] for item in preview_files(card_getter())],
                                   description=f'资质“{name}”内容核验后')

    def _remove_failed_upload(self, card_getter, receipts, responses, path, name,
                              request_guard=None):
        """清理唯一失败项；原列表稳定但成功条目缺失时返回 True，交调用方限一次补传。"""
        expected = [item.server_id for item in receipts]
        files = preview_files(card_getter())
        ids = [item['id'] for item in files]
        if ids[:len(expected)] != expected or len(ids) not in (len(expected), len(expected) + 1):
            raise PageFlowError(f'资质“{name}”失败项无法唯一定位，停止，不删除其他文件')
        if receipts:
            verify_preview_content(self.page, receipts, files[:len(expected)], self.timeout)
        if len(ids) == len(expected):
            if responses:
                receipt = UploadReceipt.from_response(path, responses[0])
                if receipt.server_id in expected:
                    raise PageFlowError(f'资质“{name}”缺失文件返回原有文件标识，停止补传')
        else:
            if responses:
                receipt = UploadReceipt.from_response(path, responses[0])
                if ids[-1] != receipt.server_id:
                    raise PageFlowError(f'资质“{name}”新增条目与当前上传标识不符，停止删除')
            card = card_getter()
            card.hover(timeout=self.timeout)
            item = card.locator('.preview-list-li').nth(len(expected))
            delete = item.locator('.delete-btn')
            if delete.count() != 1 or not delete.is_visible():
                raise PageFlowError(f'资质“{name}”找不到当前失败图片的删除按钮，停止重传')
            # 绑定当前 DOM 节点，避免后续 nth 因异步插入而指向另一张图。
            button = delete.element_handle()
            snapshot = [(item['id'], item['url']) for item in files]
            latest = [(item['id'], item['url']) for item in preview_files(card_getter())]
            if latest != snapshot or button is None:
                raise PageFlowError(f'资质“{name}”删除前文件列表发生变化，停止删除')
            if request_guard is not None:
                request_guard()
            button.click(timeout=self.timeout)
            LOGGER.info('文件[%s]：已点击失败条目的删除按钮，核对剩余文件', path.name)
        self._verify_file_receipts(card_getter, receipts, name, content=True)
        if request_guard is not None:
            request_guard()
        return bool(responses) and len(ids) == len(expected)

    def _wait_for_card_save_settle(
        self,
        container_getter,
        card_index: int,
        qualification_name: str,
        *,
        receipts=(),
        evidence: str = "",
        save_scope=None,
    ) -> None:
        """仅在保存响应通过校验后调用，等待当前卡片数据持续一致。"""

        def current_card():
            container = container_getter()
            if container is None:
                return None
            inputs = self._file_inputs_in(container)
            if len(inputs) <= card_index:
                return None
            return self._upload_container(inputs[card_index])

        stable_since: float | None = None
        last_log = 0.0
        reason = "尚未读取当前卡片"
        status_visible = False
        missing_since = None
        recovery_attempted = False

        def recover_missing_card():
            nonlocal recovery_attempted
            if (recovery_attempted or save_scope is None or not receipts
                    or self._detail_reads.pending
                    or time.monotonic() - self._detail_reads.last_finished < 1.0):
                return
            observer, cursor, identity = save_scope
            if any(not event.finished and not event.failed for event in observer.events):
                return
            state, _ = observer.state(cursor, identity, receipts, evidence)
            if state != 'saved':
                return
            recovery_attempted = True
            if not observer.readback(cursor, identity, receipts, evidence, self.timeout):
                LOGGER.warning('资质[%s]：卡片缺失且只读核对未通过，未刷新或重复写入', qualification_name)
                return
            # readback 会泵送事件，调用页面刷新前再次排除迟到写入。
            if (any(not event.finished and not event.failed for event in observer.events)
                    or observer.state(cursor, identity, receipts, evidence)[0] != 'saved'):
                return
            container = container_getter()
            if container is None:
                return
            refreshed = self._refresh_business_from_page(container)
            LOGGER.info('资质[%s]：已核实服务端保存，页面原生业务刷新%s（最多一次，无重复上传或保存）',
                        qualification_name, '已完成' if refreshed else '不可用或未完成')

        def settled() -> bool:
            nonlocal stable_since, last_log, reason, status_visible, missing_since
            issues = []
            try:
                card = current_card()
                if card is None:
                    issues.append("当前资质卡片未出现")
                    if missing_since is None:
                        missing_since = time.monotonic()
                    elif time.monotonic() - missing_since >= 2.0:
                        recover_missing_card()
                else:
                    missing_since = None
                    # 相邻资质卡的独立 loading 与本次保存无关；祖先的遮罩
                    # 会阻挡当前卡片，包含挂在 body 的全屏 loading，仍须等待。
                    loading = card.evaluate("""element => {
                      const masks = new Set(element.querySelectorAll('.el-loading-mask'));
                      for (let p = element.parentElement; p; p = p.parentElement) {
                        for (const child of p.children)
                          if (child.matches('.el-loading-mask')) masks.add(child);
                      }
                      return [...masks].some(mask => {
                        const style = getComputedStyle(mask), rect = mask.getBoundingClientRect();
                        return style.visibility !== 'hidden' && style.visibility !== 'collapse'
                          && rect.width > 0 && rect.height > 0;
                      });
                    }""")
                    if loading:
                        issues.append("当前卡片或父级加载遮罩仍可见")
                    status_visible = bool(self._visible(
                        card.get_by_text("已保存待送审", exact=True)
                    ))
                    if receipts:
                        files = preview_files(card)
                        if [item['id'] for item in files] != [r.server_id for r in receipts]:
                            issues.append(f"文件身份未一致（期望{len(receipts)}个，页面{len(files)}个）")
                        elif not all(item['ready'] for item in files):
                            issues.append("当前卡片图片未加载完成")
                        fields = self._visible(card.locator('input:not([type="file"])'))
                        if len(fields) != 1 or fields[0].input_value().strip() != evidence:
                            issues.append("举证链接尚未与本次保存一致")
                    elif card.get_by_text("资质状态", exact=True).count() and not status_visible:
                        # 无文件身份凭据的兼容页面不能仅凭输入框有文件放行。
                        issues.append("未显示已保存待送审，且无文件身份凭据")
            except Exception as exc:
                # DOM 重建窗口继续等待，只记录异常类型，不输出动态 URL/表单值。
                issues.append(f"读取当前卡片遇到{type(exc).__name__}")
            if issues:
                stable_since = None
                reason = "；".join(issues)
                now = time.monotonic()
                if now - last_log >= 10:
                    LOGGER.info('资质[%s]：保存后等待页面回填：%s', qualification_name, reason)
                    last_log = now
                return False
            if stable_since is None:
                stable_since = time.monotonic()
            reason = "文件和表单已匹配，等待连续稳定1秒"
            return time.monotonic() - stable_since >= 1.0

        try:
            self._wait_until(
                settled,
                f"等待资质“{qualification_name}”保存后页面刷新稳定超时",
            )
        except PageFlowError as exc:
            raise PageFlowError(f"{exc}：{reason}；未重复上传或保存") from exc
        if receipts and not status_visible:
            LOGGER.info('资质[%s]：保存响应及文件、举证已核验，页面状态文案尚未同步', qualification_name)
        LOGGER.info('资质[%s]：保存后当前卡片已稳定', qualification_name)

    def _refresh_business_from_page(self, container) -> bool:
        """使用已核查的 BusinessFormCard.onInit，只让页面重新读取业务。"""
        root = container.locator('.business-form-card')
        # 新增页的 container 本身就是业务卡；编辑页的 container 是 page。
        if hasattr(container, 'evaluate') and not hasattr(container, 'url'):
            if container.evaluate("e => e.matches('.business-form-card')"):
                root = container
        visible = self._visible(root)
        if len(visible) != 1:
            return False
        return visible[0].evaluate("""async (element, timeout) => {
          const matches = new Set(), seen = new Set();
          const consider = c => {
            const owns = c?.subTree?.el === element
              || (Array.isArray(c?.subTree?.children) && c.subTree.children.some(v=>v?.el===element));
            if (c?.type?.__name === 'BusinessFormCard' && owns
                && typeof c.vnode?.props?.onInit === 'function') matches.add(c);
          };
          for (let c=element.__vueParentComponent;c;c=c.parent) consider(c);
          let root=element;while(root&&!root._vnode)root=root.parentElement;
          const walk=v=>{if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
            if(v.component){consider(v.component);walk(v.component.subTree);}
            if(Array.isArray(v.children))v.children.forEach(walk);
            if(v.suspense)walk(v.suspense.activeBranch);};
          walk(root?._vnode);
          if(matches.size!==1)return false;
          const component=[...matches][0];if(component.isUnmounted)return false;
          let timer;
          try{return await Promise.race([
            Promise.resolve(component.vnode.props.onInit()).then(()=>true,()=>false),
            new Promise(resolve=>{timer=setTimeout(()=>resolve(false),timeout);})]);
          }finally{clearTimeout(timer);}
        }""", min(self.timeout, 10_000))

    def upload_type(self, qualification_type: QualificationType, business_index: int) -> None:
        self._click_business_tab(business_index)
        self._upload_type_in(
            qualification_type,
            business_index,
            lambda: self._business_container(business_index),
        )

    def _upload_type_in(
        self,
        qualification_type: QualificationType,
        business_key: int,
        container_getter,
        *,
        resume_existing: bool = False,
    ) -> None:
        qualifications = qualification_type.qualifications
        if not qualifications:
            raise PageFlowError(f"资质类型“{qualification_type.type_name}”没有文件")
        main_form_count = self._wait_for_initial_main_form_count(container_getter)
        if main_form_count > len(qualifications):
            raise PageFlowError(
                f"业务“{qualification_type.type_name}”需要{main_form_count}个内置必填资质，"
                f"输入仅提供{len(qualifications)}个资质目录"
            )
        if resume_existing:
            if len(self._file_inputs_in(container_getter())) > len(qualifications):
                raise PageFlowError('已保存资质卡片多于输入目录，停止，不删除已有资料')
        else:
            self._discard_empty_initial_supplements(container_getter)
        for index, qualification in enumerate(qualifications):
            LOGGER.info("业务[%s] 资质[%s]：准备第 %s 张卡片，共 %s 个文件", qualification_type.type_name, qualification.index_name, index + 1, len(qualification.files))
            # 一个资质目录对应一张卡片，目录内文件逐个上传并等待回填；
            # 只有下一个资质目录才创建补充资质卡片。
            try:
                self._ensure_upload_form_count_in(container_getter, index + 1)
            except PageFlowError as exc:
                raise PageFlowError(
                    f"业务“{qualification_type.type_name}”创建第{index + 1}个"
                    f"资质卡片失败：{exc}"
                ) from exc
            self._upload_qualification_in(qualification_type, business_key, index, container_getter,
                                          resume_existing=resume_existing)

    def _upload_qualification_in(self, qualification_type, business_key, index, container_getter,
                                 *, resume_existing=False):
        """上传一张指定卡片；监听在首个文件及任何鼠标操作之前建立。"""
        qualification = qualification_type.qualifications[index]
        with CardSaveObserver(self.page) as observer:
            inputs = self._file_inputs_in(container_getter())
            if len(inputs) < index + 1:
                raise PageFlowError(
                    f"业务“{qualification_type.type_name}”第{index + 1}个资质卡片数量异常："
                    f"至少需要 {index + 1}，实际 {len(inputs)}"
                )
            paths = tuple(path.resolve() for path in qualification.files)
            def current_card():
                return self._upload_container(self._file_inputs_in(container_getter())[index])

            def uploaded_count():
                card = current_card()
                preview = card.locator(".preview-container")
                if not preview.count():
                    return None
                self._preview_cards.add((business_key, index))
                counts = [int(match.group(1))
                          for item in self._visible(preview.locator(".file-count"))
                          if (match := re.fullmatch(r"\s*(\d+)\s*/\s*\d+\s*", item.inner_text()))]
                if len(counts) == 1:
                    return counts[0]
                if not counts and not preview.locator("img, a[href], .el-upload-list__item").count():
                    return 0
                return None

            receipts = []
            existing = preview_files(current_card())
            if existing:
                if not resume_existing:
                    raise PageFlowError('上传目标卡片非空，未重复上传')
                if len(existing) > len(paths) or not all(item['id'] for item in existing):
                    raise PageFlowError('已保存文件数量或身份与输入不符，未修改已有资料')
                if not self._visible(current_card().get_by_text('已保存待送审', exact=True)):
                    raise PageFlowError('当前卡片不是已保存待送审状态，不能确认续传起点')
                receipts = [UploadReceipt(path, hashlib.sha256(path.read_bytes()).hexdigest(), item['id'])
                            for path, item in zip(paths, existing)]
                self._verify_file_receipts(current_card, receipts, qualification.index_name, content=True)
                self._preview_cards.add((business_key, index))
                evidence = qualification.evidence_url or ''
                field = self._unique_visible(current_card().locator('input:not([type="file"])'), '已有资质举证链接')
                if field.input_value().strip() != evidence:
                    self._save_qualification_card(current_card, container_getter, evidence, receipts, qualification.index_name)
                self._wait_for_card_save_settle(container_getter, index, qualification.index_name,
                                                 receipts=receipts, evidence=evidence)
                LOGGER.info('业务[%s] 资质[%s]：已核验并恢复 %s 个已保存文件，仅续传缺失文件',
                            qualification_type.type_name, qualification.index_name, len(receipts))
            batches = [(path,) for path in paths[len(receipts):]]
            uploaded_total = len(receipts)
            for batch in batches:
                # 身份必须在上传前快照：首次保存后页面会获得新的 lice_index。
                save_scope = (observer, observer.checkpoint(), current_card().evaluate(CARD_IDENTITY_JS))
                description = f"业务[{qualification_type.type_name}] 资质[{qualification.index_name}] 文件[{', '.join(path.name for path in batch)}]"

                def trigger():
                    self._scroll_upload_to_bottom(current_card())
                    current_card().hover(timeout=self.timeout)
                    current_input = self._file_inputs_in(container_getter())[index]
                    # 清空原生选择值使相同文件可再次触发 change，不删除已上传预览。
                    current_input.evaluate("element => { element.value = ''; }")
                    current_input.set_input_files([str(path) for path in batch])

                def verify_current(responses):
                    candidate = UploadReceipt.from_response(batch[0], responses[0])
                    attempted = [*receipts, candidate]
                    # 每张立即检查可访问性与内容，不等整张资质卡保存后才发现坏图。
                    verify_preview_content(self.page, attempted, preview_files(current_card()), self.timeout)
                    self._verify_file_receipts(current_card, attempted, qualification.index_name)

                has_preview = bool(current_card().locator('.preview-container').count())

                responses = upload_with_retry(
                    self.page, trigger, uploaded_count,
                    lambda response: self._submitlice_response(response, "文件上传"),
                    description=description, timeout_ms=self.timeout, file_count=len(batch),
                    verify_success=verify_current if has_preview else None,
                    cleanup_failed=(lambda responses, guard: self._remove_failed_upload(
                        current_card, receipts, responses, batch[0], qualification.index_name, guard
                    )) if has_preview else None,
                )
                uploaded_total += len(batch)
                self._wait_for_uploaded_file_state(current_card(), uploaded_total, qualification.index_name)
                if (business_key, index) in self._preview_cards:
                    receipts.append(UploadReceipt.from_response(batch[0], responses[0]))
                    self._verify_file_receipts(current_card, receipts, qualification.index_name)
                    LOGGER.info('%s：源文件 SHA-256 %s，文件身份及预览已稳定', description, receipts[-1].sha256[:12])

                evidence = qualification.evidence_url or ""
                LOGGER.info("业务[%s] 资质[%s]：%s举证链接", qualification_type.type_name, qualification.index_name, "填写" if evidence else "清空/不填写")
                self._save_qualification_card(
                    current_card, container_getter, evidence, receipts, qualification.index_name,
                    save_scope=save_scope,
                )
                self._wait_for_card_save_settle(
                    container_getter, index, qualification.index_name,
                    receipts=receipts, evidence=evidence,
                    save_scope=save_scope,
                )
                self._verify_saved_file_count(current_card(), uploaded_total, qualification.index_name,
                                             required=(business_key, index) in self._preview_cards)
                if receipts:
                    self._verify_file_receipts(current_card, receipts, qualification.index_name, content=True)
                # 页面回填与内容核验也会泵送迟到事件，再确认没有较晚写入覆盖本次结果。
                self._save_observed_card(current_card, evidence, receipts, qualification.index_name,
                                         save_scope, allow_trigger=False)
                LOGGER.info('%s：逐文件保存成功，累计 %s 个文件', description, uploaded_total)
            if receipts:
                self._verify_file_receipts(current_card, receipts, qualification.index_name, content=True)
                self._saved_file_receipts[(business_key, index)] = tuple(receipts)
            LOGGER.info("业务[%s] 资质[%s]：自动保存成功，页面已稳定", qualification_type.type_name, qualification.index_name)
            self._saved_uploads[(business_key, index)] = paths
            evidence = qualification.evidence_url or ""
            self._saved_evidence[(business_key, index)] = evidence

    def validate_final_collection(
        self,
        assignments: tuple[tuple[QualificationType, int], ...],
    ) -> None:
        """最终送审前重扫业务和表单，并核对本次保存凭据与举证链接。"""

        expected_indices = {business_index for _, business_index in assignments}
        actual_indices = set(self._business_tabs())
        if actual_indices != expected_indices:
            raise PageFlowError(
                "最终业务集合不一致："
                f"期望 {sorted(expected_indices)}，实际 {sorted(actual_indices)}"
            )

        expected_uploads: dict[tuple[int, int], tuple[Path, ...]] = {}
        expected_evidence: dict[tuple[int, int], str] = {}
        for qualification_type, business_index in assignments:
            self._click_business_tab(business_index)
            container = self._business_container(business_index)
            if container is None or not self._business_type_matches(
                container,
                qualification_type.type_name,
            ):
                raise PageFlowError(
                    f"最终业务{business_index}类型与“{qualification_type.type_name}”不一致"
                )

            qualifications = qualification_type.qualifications
            inputs = self._file_inputs(business_index)
            if len(inputs) != len(qualifications):
                raise PageFlowError(
                    f"最终业务“{qualification_type.type_name}”表单数量不一致："
                    f"期望 {len(qualifications)}，实际 {len(inputs)}"
                )
            for index, qualification in enumerate(qualifications):
                key = (business_index, index)
                expected_uploads[key] = tuple(
                    path.resolve() for path in qualification.files
                )
                evidence = qualification.evidence_url or ""
                expected_evidence[key] = evidence
                upload_container = self._upload_container(inputs[index])
                self._verify_saved_file_count(upload_container, len(qualification.files), qualification.index_name,
                                             required=key in self._preview_cards)
                if key in self._saved_file_receipts:
                    self._verify_file_receipts(lambda: self._upload_container(self._file_inputs(business_index)[index]),
                                               self._saved_file_receipts[key], qualification.index_name, content=True)
                evidence_input = self._unique_visible(
                    upload_container.locator('input:not([type="file"])'),
                    f"最终业务{business_index}第{index + 1}张文件的举证链接输入框",
                )
                if not evidence_urls_match(evidence_input.input_value(), evidence):
                    raise PageFlowError(
                        f"最终举证链接不一致：{qualification_type.type_name}/"
                        f"{qualification.index_name}"
                    )

        if self._saved_uploads != expected_uploads:
            raise PageFlowError("最终文件保存集合与完整输入不一致")
        if self._saved_evidence != expected_evidence:
            raise PageFlowError("最终举证链接保存集合与完整输入不一致")

    def _validate_uploaded_scope(
        self,
        qualification_type: QualificationType,
        business_key: int,
        container,
    ) -> None:
        qualifications = qualification_type.qualifications
        inputs = self._file_inputs_in(container)
        if len(inputs) != len(qualifications):
            raise PageFlowError(
                f"编辑业务“{qualification_type.type_name}”表单数量不一致："
                f"期望 {len(qualifications)}，实际 {len(inputs)}"
            )
        for index, qualification in enumerate(qualifications):
            key = (business_key, index)
            expected_paths = tuple(path.resolve() for path in qualification.files)
            if self._saved_uploads.get(key) != expected_paths:
                raise PageFlowError(
                    f"编辑业务文件保存记录不一致：{qualification.index_name}"
                )
            evidence = qualification.evidence_url or ""
            if self._saved_evidence.get(key) != evidence:
                raise PageFlowError(
                    f"编辑业务举证保存记录不一致：{qualification.index_name}"
                )
            upload_container = self._upload_container(inputs[index])
            self._verify_saved_file_count(upload_container, len(qualification.files), qualification.index_name,
                                         required=key in self._preview_cards)
            if key in self._saved_file_receipts:
                self._verify_file_receipts(lambda: self._upload_container(self._file_inputs_in(container)[index]),
                                           self._saved_file_receipts[key], qualification.index_name, content=True)
            evidence_input = self._unique_visible(
                upload_container.locator('input:not([type="file"])'),
                f"编辑业务第{index + 1}张文件的举证链接输入框",
            )
            if not evidence_urls_match(evidence_input.input_value(), evidence):
                raise PageFlowError(
                    f"编辑业务举证链接回读不一致：{qualification.index_name}"
                )

    def _return_from_promotion_edit(self) -> None:
        cancel = self._unique_visible(
            self.page.get_by_role("button", name="取消", exact=True),
            "推广审查编辑页“取消”按钮",
        )
        cancel.click(timeout=self.timeout)
        self._wait_until(
            lambda: (
                urlsplit(self.page.url).hostname == PERMIT_HOST
                and urlsplit(self.page.url).fragment.startswith(
                    "/lice/invest_lice_list/"
                )
            ),
            "保存推广审查后未返回投放资质详情页",
        )

    def fill_all(self, company: CompanyInput) -> None:
        LOGGER.info("新版投放资质：检查输入业务类型，进入新增或已有草稿页面")
        types = ordered_new_audit_types(company)
        resumed_promotion = self.enter_add_business_page()
        assignments: list[tuple[QualificationType, int]] = []
        LOGGER.info("推广审查：%s", "恢复已有草稿" if resumed_promotion else "准备默认业务")
        if resumed_promotion:
            self._upload_type_in(types[0], 0, lambda: self.page, resume_existing=True)
            self._validate_uploaded_scope(types[0], 0, self.page)
            self._return_from_promotion_edit()
            self._saved_uploads.clear()
            self._saved_file_receipts.clear()
            self._preview_cards.clear()
            self._saved_evidence.clear()
            self.enter_add_business_page(allow_resume=False)
            LOGGER.info("清理新增页面默认业务")
            self.remove_all_default_businesses()
        else:
            promotion_index = self.prepare_promotion_business(types[0])
            assignments.append((types[0], promotion_index))
            self.upload_type(types[0], promotion_index)
        for qualification_type in types[1:]:
            LOGGER.info("业务[%s]：新增业务并选择精确类型", qualification_type.type_name)
            business_index = self.add_business(qualification_type)
            assignments.append((qualification_type, business_index))
            self.upload_type(qualification_type, business_index)
        LOGGER.info("全部业务上传完成：开始核对最终业务、资质和文件集合")
        self.validate_final_collection(tuple(assignments))
        LOGGER.info("最终集合校验通过")
