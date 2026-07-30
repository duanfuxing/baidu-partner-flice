"""行业资质区域扫描、预检和经营业务操作。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable

from .errors import PageFlowError
from .models import CompanyInput, QualificationType
from .type_mapping import (
    BusinessTypeMapping,
    mapping_for_input,
    mapping_for_page,
    normalize_business_name,
    page_name_matches,
)


@dataclass(frozen=True)
class BusinessPanelSnapshot:
    dom_id: str
    header_text: str
    display_name: str
    deletable: bool
    expanded: bool


@dataclass(frozen=True)
class QualificationCardSnapshot:
    dom_id: str
    qualification_no: str | None
    qualification_name: str | None
    expiry_text: str | None
    evidence_url: str | None
    status: str | None
    deletable: bool
    file_count: int
    file_identifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndustryExecutionPlan:
    existing_types: tuple[tuple[QualificationType, BusinessPanelSnapshot], ...]
    delete_businesses: tuple[BusinessPanelSnapshot, ...]
    add_types: tuple[tuple[QualificationType, BusinessTypeMapping], ...]
    mandatory_businesses: tuple[BusinessPanelSnapshot, ...]


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_unique_input_qualification_keys(company: CompanyInput) -> None:
    for qualification_type in company.qualification_types:
        keys = [
            f"{item.qualification_no}\u0000{item.qualification_name}"
            for item in qualification_type.qualifications
        ]
        duplicates = _duplicates(keys)
        if duplicates:
            labels = [
                f"{value.split(chr(0), 1)[0]} / {value.split(chr(0), 1)[1]}"
                for value in duplicates
            ]
            raise PageFlowError(
                f"经营业务“{qualification_type.type_name}”的 input.json 存在重复"
                "“资质编号 + 资质名称”："
                + "、".join(labels)
            )


def build_execution_plan(
    company: CompanyInput,
    panels: tuple[BusinessPanelSnapshot, ...],
) -> IndustryExecutionPlan:
    """用只读页面快照生成完整经营业务执行计划。"""

    validate_unique_input_qualification_keys(company)
    input_mappings: dict[str, tuple[QualificationType, BusinessTypeMapping]] = {}
    for qualification_type in company.qualification_types:
        mapping = mapping_for_input(qualification_type.type_name)
        key = normalize_business_name(mapping.canonical_page_name)
        if key in input_mappings:
            raise PageFlowError(
                f"多个输入类型映射到同一经营业务：{input_mappings[key][0].type_name}、"
                f"{qualification_type.type_name}"
            )
        input_mappings[key] = (qualification_type, mapping)

    page_by_key: dict[str, BusinessPanelSnapshot] = {}
    mandatory: list[BusinessPanelSnapshot] = []
    delete_businesses: list[BusinessPanelSnapshot] = []
    for panel in panels:
        page_mapping = mapping_for_page(panel.display_name)
        if page_mapping is None:
            raise PageFlowError(f"页面存在未配置的经营业务，禁止自动删除：{panel.display_name}")
        key = normalize_business_name(page_mapping.canonical_page_name)
        if key in page_by_key:
            raise PageFlowError(f"页面存在重复经营业务：{panel.display_name}")
        page_by_key[key] = panel
        if page_mapping.mandatory or not panel.deletable:
            mandatory.append(panel)
        elif key not in input_mappings:
            delete_businesses.append(panel)

    existing: list[tuple[QualificationType, BusinessPanelSnapshot]] = []
    add_types: list[tuple[QualificationType, BusinessTypeMapping]] = []
    for key, (qualification_type, mapping) in input_mappings.items():
        panel = page_by_key.get(key)
        if panel is None:
            add_types.append((qualification_type, mapping))
        elif not page_name_matches(mapping, panel.display_name):
            raise PageFlowError(
                f"经营业务映射不一致：输入“{qualification_type.type_name}”，页面“{panel.display_name}”"
            )
        else:
            existing.append((qualification_type, panel))

    return IndustryExecutionPlan(
        existing_types=tuple(existing),
        delete_businesses=tuple(delete_businesses),
        add_types=tuple(add_types),
        mandatory_businesses=tuple(mandatory),
    )


_SCAN_BUSINESSES_SCRIPT = r"""
() => {
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const all = Array.from(document.querySelectorAll('body *'));
  const ownText = element => normalize(
    Array.from(element.childNodes)
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent)
      .join(' ')
  );
  const candidates = all.filter(element => {
    const firstLine = normalize(element.innerText).split('\n')[0];
    return /^经营业务\s*\d+\s*[：:]/.test(ownText(element) || firstLine);
  });
  const headers = candidates.filter(element =>
    !candidates.some(other => other !== element && element.contains(other))
  );
  return headers.map((header, index) => {
    const headerContainer =
      header.closest('.el-collapse-item__header') || header.parentElement || header;
    let root = header.closest('.el-collapse-item') || header.parentElement || header;
    let depth = 0;
    while (!header.closest('.el-collapse-item') && root.parentElement && depth < 4) {
      const parent = root.parentElement;
      const count = headers.filter(item => parent.contains(item)).length;
      if (count !== 1) break;
      root = parent;
      depth += 1;
    }
    const id = `codex-business-${index}`;
    root.setAttribute('data-codex-business-id', id);
    headerContainer.setAttribute('data-codex-business-header', id);
    const text = normalize(root.innerText);
    const headerText = normalize(headerContainer.innerText);
    const match = headerText.match(
      /^经营业务\s*\d+\s*[：:]\s*(.*?)(?:\s*删除业务)?$/
    );
    const name = normalize(match ? match[1] : headerText);
    const deletable = text.includes('删除业务');
    const expanded = text.includes('资质编号') || text.includes('上传备用资质文件');
    return {domId: id, headerText, displayName: name, deletable, expanded};
  });
}
"""


_SCAN_CARDS_SCRIPT = r"""
root => {
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const elements = Array.from(root.querySelectorAll('div'));
  let candidates = elements.filter(element => {
    const text = normalize(element.innerText);
    if (!text.includes('资质状态') && !text.includes('资质编号')) return false;
    const style = getComputedStyle(element);
    return style.borderStyle.includes('dashed') || style.borderStyle.includes('solid');
  });
  candidates = candidates.filter(element =>
    !candidates.some(other => other !== element && element.contains(other))
  );
  if (!candidates.length) {
    candidates = elements.filter(element => {
      const text = normalize(element.innerText);
      if (!text.includes('资质编号')) return false;
      return !Array.from(element.children).some(child => normalize(child.innerText).includes('资质编号'));
    });
  }
  const field = (text, label, nextLabels) => {
    const end = nextLabels.length ? `(?=${nextLabels.join('|')}|$)` : '$';
    const match = text.match(new RegExp(`${label}\\s*([^]*?)${end}`));
    return match ? normalize(match[1]) || null : null;
  };
  return candidates.map((card, index) => {
    const id = `codex-card-${index}`;
    card.setAttribute('data-codex-card-id', id);
    const text = normalize(card.innerText);
    const fileIdentifiers = Array.from(card.querySelectorAll('img, a[href]'))
      .flatMap(element => [
        element.getAttribute('alt'),
        element.getAttribute('title'),
        element.getAttribute('src'),
        element.getAttribute('href')
      ])
      .filter(Boolean)
      .filter(value => !value.startsWith('data:'))
      .map(value => {
        try {
          const parsed = new URL(value, location.href);
          return decodeURIComponent(parsed.pathname.split('/').filter(Boolean).pop() || value);
        } catch (_) {
          return value;
        }
      })
      .filter(Boolean);
    return {
      domId: id,
      qualificationNo: field(text, '资质编号', ['资质名称', '有效期至', '举证链接']),
      qualificationName: field(text, '资质名称', ['有效期至', '举证链接']),
      expiryText: field(text, '有效期至', ['举证链接']),
      evidenceUrl: field(text, '举证链接', []),
      status: field(text, '资质状态', ['资质编号', '资质名称']),
      deletable: text.includes('删除') || !!card.querySelector('[class*="delete"], .el-icon-delete'),
      fileCount: card.querySelectorAll('img').length,
      fileIdentifiers: Array.from(new Set(fileIdentifiers))
    };
  });
}
"""


class IndustryQualificationPage:
    def __init__(self, page, timeout: int = 30_000) -> None:
        self.page = page
        self.timeout = timeout

    def wait_until_ready(self) -> None:
        self.page.get_by_text("行业资质", exact=True).first.wait_for(
            state="visible", timeout=self.timeout
        )

    def scan_businesses(self) -> tuple[BusinessPanelSnapshot, ...]:
        self.wait_until_ready()
        raw_items = self.page.evaluate(_SCAN_BUSINESSES_SCRIPT)
        return tuple(
            BusinessPanelSnapshot(
                dom_id=item["domId"],
                header_text=item["headerText"],
                display_name=item["displayName"],
                deletable=bool(item["deletable"]),
                expanded=bool(item["expanded"]),
            )
            for item in raw_items
        )

    def _business_root(self, panel: BusinessPanelSnapshot):
        locator = self.page.locator(f'[data-codex-business-id="{panel.dom_id}"]')
        if locator.count() != 1:
            raise PageFlowError(f"经营业务定位失效：{panel.display_name}")
        return locator

    def find_business(self, display_name: str) -> BusinessPanelSnapshot:
        matches = [
            panel
            for panel in self.scan_businesses()
            if normalize_business_name(panel.display_name) == normalize_business_name(display_name)
        ]
        if len(matches) != 1:
            raise PageFlowError(f"无法唯一定位经营业务“{display_name}”，匹配数：{len(matches)}")
        return matches[0]

    def expand_business(self, panel: BusinessPanelSnapshot) -> BusinessPanelSnapshot:
        current = self.find_business(panel.display_name)
        if not current.expanded:
            root = self._business_root(current)
            header = root.locator(f'[data-codex-business-header="{current.dom_id}"]')
            if header.count() == 0:
                header = root.locator("xpath=./*[1]")
            header.first.click(timeout=self.timeout)
            self.page.wait_for_timeout(300)
            current = self.find_business(panel.display_name)
        return current

    def scan_cards(self, panel: BusinessPanelSnapshot) -> tuple[QualificationCardSnapshot, ...]:
        current = self.expand_business(panel)
        root = self._business_root(current)
        raw_items = root.evaluate(_SCAN_CARDS_SCRIPT)
        return tuple(
            QualificationCardSnapshot(
                dom_id=item["domId"],
                qualification_no=item.get("qualificationNo"),
                qualification_name=item.get("qualificationName"),
                expiry_text=item.get("expiryText"),
                evidence_url=item.get("evidenceUrl"),
                status=item.get("status"),
                deletable=bool(item["deletable"]),
                file_count=int(item["fileCount"]),
                file_identifiers=tuple(item.get("fileIdentifiers") or ()),
            )
            for item in raw_items
        )

    def _confirm_dialog(self, expected_text: str | None = None) -> None:
        dialog = self.page.locator(".el-message-box:visible, [role=dialog]:visible").last
        try:
            dialog.wait_for(state="visible", timeout=2_000)
        except Exception:
            return
        text = dialog.inner_text()
        generic_delete_confirmation = bool(
            re.search(r"(删除|移除).{0,20}(资质|文件)|(?:确认|确定|是否).{0,20}(删除|移除)", text)
        )
        if expected_text and expected_text not in text and not generic_delete_confirmation:
            cancel = dialog.get_by_text(re.compile(r"取消|关闭"), exact=False)
            if cancel.count():
                cancel.last.click()
            dialog_summary = re.sub(r"\s+", " ", text).strip()
            raise PageFlowError(
                f"删除确认信息无法确认属于资质删除，目标：{expected_text}，"
                f"弹窗：{dialog_summary}"
            )
        confirm = dialog.get_by_text(re.compile(r"确定|确认|删除"), exact=False)
        if confirm.count() == 0:
            raise PageFlowError("删除确认弹窗中找不到确认按钮")
        confirm.last.click(timeout=self.timeout)

    def delete_business(self, panel: BusinessPanelSnapshot) -> None:
        current = self.find_business(panel.display_name)
        if not current.deletable:
            raise PageFlowError(f"经营业务不可删除：{current.display_name}")
        root = self._business_root(current)
        button = root.get_by_text("删除业务", exact=True)
        if button.count() != 1:
            raise PageFlowError(f"经营业务删除按钮不唯一：{current.display_name}")
        button.click(timeout=self.timeout)
        self._confirm_dialog(current.display_name)
        self.page.wait_for_timeout(300)
        if any(
            normalize_business_name(item.display_name) == normalize_business_name(current.display_name)
            for item in self.scan_businesses()
        ):
            raise PageFlowError(f"删除经营业务后仍然存在：{current.display_name}")

    def validate_business_deletion_target(self, panel: BusinessPanelSnapshot) -> None:
        current = self.find_business(panel.display_name)
        if not current.deletable:
            raise PageFlowError(f"经营业务不可删除：{current.display_name}")
        root = self._business_root(current)
        button = root.get_by_text("删除业务", exact=True)
        visible = [
            button.nth(index)
            for index in range(button.count())
            if button.nth(index).is_visible()
        ]
        if len(visible) != 1:
            raise PageFlowError(f"经营业务删除按钮无法唯一定位：{current.display_name}")

    def validate_card_deletion_target(
        self,
        panel: BusinessPanelSnapshot,
        card: QualificationCardSnapshot,
    ) -> None:
        if not card.qualification_no or not card.deletable:
            raise PageFlowError(
                f"已有资质不可安全删除：{card.qualification_no or '无编号'}"
            )
        root = self._business_root(self.find_business(panel.display_name))
        card_locator = root.locator(f'[data-codex-card-id="{card.dom_id}"]')
        if card_locator.count() != 1:
            raise PageFlowError(f"无法定位旧资质删除目标：{card.qualification_no}")
        delete_button = card_locator.locator('[class*="delete"], .el-icon-delete')
        if delete_button.count() == 0:
            delete_button = card_locator.get_by_text("删除", exact=True)
        visible = [
            delete_button.nth(index)
            for index in range(delete_button.count())
            if delete_button.nth(index).is_visible()
        ]
        if len(visible) != 1:
            raise PageFlowError(f"旧资质删除入口无法唯一定位：{card.qualification_no}")

    def validate_card_edit_target(
        self,
        panel: BusinessPanelSnapshot,
        card: QualificationCardSnapshot,
    ) -> None:
        root = self._business_root(self.find_business(panel.display_name))
        card_locator = root.locator(f'[data-codex-card-id="{card.dom_id}"]')
        if card_locator.count() != 1:
            raise PageFlowError(
                f"无法定位资质编辑目标：{card.qualification_no or '系统空白卡'}"
            )
        edit = card_locator.locator('[class*="edit"], .el-icon-edit')
        if edit.count() == 0:
            edit = card_locator.get_by_text("编辑", exact=True)
        visible = [
            edit.nth(index)
            for index in range(edit.count())
            if edit.nth(index).is_visible()
        ]
        # 系统空白卡允许点击卡片本身打开；已有资质必须有明确编辑入口。
        if card.qualification_no and len(visible) != 1:
            raise PageFlowError(f"资质编辑入口无法唯一定位：{card.qualification_no}")

    def validate_backup_upload_target(self, panel: BusinessPanelSnapshot) -> None:
        root = self._business_root(self.find_business(panel.display_name))
        upload = root.get_by_text("上传备用资质文件", exact=False)
        visible = [
            upload.nth(index)
            for index in range(upload.count())
            if upload.nth(index).is_visible()
        ]
        if len(visible) != 1:
            raise PageFlowError(
                f"经营业务“{panel.display_name}”的备用资质入口无法唯一定位"
            )

    def delete_card(self, panel: BusinessPanelSnapshot, card: QualificationCardSnapshot) -> None:
        if not card.qualification_no:
            raise PageFlowError("禁止删除无资质编号的系统空白卡")
        current = self.find_business(panel.display_name)
        self.expand_business(current)
        before_cards = self.scan_cards(current)
        before_matching = [
            item
            for item in before_cards
            if item.qualification_no == card.qualification_no
            and item.qualification_name == card.qualification_name
        ]
        before_filled_count = sum(
            1 for item in before_cards if item.qualification_no
        )
        deletion_candidates = [
            item for item in before_matching if item.deletable
        ]
        target_by_dom_id = [
            item for item in deletion_candidates if item.dom_id == card.dom_id
        ]
        if len(target_by_dom_id) == 1:
            card = target_by_dom_id[0]
        elif len(deletion_candidates) == 1:
            card = deletion_candidates[0]
        else:
            raise PageFlowError(
                f"无法唯一定位待删除资质：{card.qualification_no}，"
                f"同标识可删除卡数量：{len(deletion_candidates)}"
            )
        root = self._business_root(self.find_business(panel.display_name))
        card_locator = root.locator(f'[data-codex-card-id="{card.dom_id}"]')
        if card_locator.count() != 1:
            raise PageFlowError(f"待删除资质卡片定位失效：{card.qualification_no}")
        delete_button = card_locator.locator('[class*="delete"], .el-icon-delete')
        if delete_button.count() == 0:
            delete_button = card_locator.get_by_text("删除", exact=True)
        if delete_button.count() == 0:
            raise PageFlowError(f"已有资质没有删除入口：{card.qualification_no}")
        delete_button.last.click(timeout=self.timeout)
        self._confirm_dialog(card.qualification_no)
        expected_matching_count = len(before_matching) - 1
        expected_filled_count = before_filled_count - 1
        deadline = time.monotonic() + min(self.timeout, 5_000) / 1000
        after_matching_count = len(before_matching)
        after_filled_count = before_filled_count
        while time.monotonic() < deadline:
            after_cards = self.scan_cards(self.find_business(panel.display_name))
            after_matching_count = sum(
                1
                for item in after_cards
                if item.qualification_no == card.qualification_no
                and item.qualification_name == card.qualification_name
            )
            after_filled_count = sum(
                1 for item in after_cards if item.qualification_no
            )
            if (
                after_matching_count == expected_matching_count
                and after_filled_count == expected_filled_count
            ):
                return
            self.page.wait_for_timeout(100)
        raise PageFlowError(
            f"删除资质后卡片数量未按预期减少：{card.qualification_no}；"
            f"同标识 {len(before_matching)}→{after_matching_count}，"
            f"已填卡 {before_filled_count}→{after_filled_count}"
        )

    def _business_selector_input(self):
        label = self.page.get_by_text(
            re.compile(r"^经营业务\s*[：:]?$"),
            exact=False,
        )
        if label.count() == 0:
            raise PageFlowError("找不到“经营业务”选择框标签")
        selector = label.first.locator("xpath=following::input[1]")
        if selector.count() == 0:
            raise PageFlowError("找不到经营业务搜索框")
        return selector.first

    def ensure_add_candidate(self, mapping: BusinessTypeMapping) -> str:
        selector = self._business_selector_input()
        selector.click()
        selector.fill(mapping.input_name)
        matches = self._matching_business_options(mapping)
        self.page.keyboard.press("Escape")
        if len(matches) != 1:
            raise PageFlowError(
                f"经营业务候选项无法唯一匹配“{mapping.input_name}”，匹配数：{len(matches)}"
            )
        return matches[0][1]

    def _matching_business_options(self, mapping: BusinessTypeMapping):
        deadline = time.monotonic() + self.timeout / 1000
        while time.monotonic() < deadline:
            option_sets = [
                self.page.locator(
                    ".el-select-dropdown__item:visible, "
                    "[role=option]:visible, "
                    ".el-select-dropdown:visible li:visible"
                )
            ]
            for alias in mapping.page_names:
                option_sets.append(self.page.get_by_text(alias, exact=True))
            matches_by_name: dict[str, tuple[object, str]] = {}
            for options in option_sets:
                for index in range(options.count()):
                    option = options.nth(index)
                    if not option.is_visible():
                        continue
                    text = option.inner_text().strip()
                    if not page_name_matches(mapping, text):
                        continue
                    normalized = normalize_business_name(text)
                    matches_by_name.setdefault(normalized, (option, text))
            if matches_by_name:
                return list(matches_by_name.values())
            self.page.wait_for_timeout(200)
        raise PageFlowError(f"经营业务没有搜索候选项：{mapping.input_name}")

    def validate_add_control(self) -> None:
        add_button = self.page.get_by_text("添加", exact=True)
        visible = [
            add_button.nth(index)
            for index in range(add_button.count())
            if add_button.nth(index).is_visible()
        ]
        if len(visible) != 1:
            raise PageFlowError("找不到唯一可见的经营业务“添加”按钮")

    def add_business(self, mapping: BusinessTypeMapping) -> BusinessPanelSnapshot:
        self.ensure_add_candidate(mapping)
        selector = self._business_selector_input()
        selector.click()
        selector.fill(mapping.input_name)
        matches = self._matching_business_options(mapping)
        if len(matches) != 1:
            raise PageFlowError(f"经营业务候选项在添加时不唯一：{mapping.input_name}")
        matches[0][0].click()
        self.validate_add_control()
        add_button = self.page.get_by_text("添加", exact=True)
        visible_add = [
            add_button.nth(index)
            for index in range(add_button.count())
            if add_button.nth(index).is_visible()
        ]
        visible_add[0].click(timeout=self.timeout)
        self.page.wait_for_timeout(500)
        return self.find_business(mapping.canonical_page_name)

    def open_card_editor(
        self,
        panel: BusinessPanelSnapshot,
        card: QualificationCardSnapshot,
    ):
        current = self.expand_business(self.find_business(panel.display_name))
        cards = self.scan_cards(current)
        matches = [
            item
            for item in cards
            if item.qualification_no == card.qualification_no
            and item.qualification_name == card.qualification_name
        ]
        if len(matches) != 1:
            raise PageFlowError(
                f"无法唯一定位待编辑资质：{card.qualification_no or card.dom_id}"
            )
        root = self._business_root(self.find_business(panel.display_name))
        card_locator = root.locator(f'[data-codex-card-id="{matches[0].dom_id}"]')
        edit = card_locator.locator('[class*="edit"], .el-icon-edit')
        if edit.count() == 0:
            edit = card_locator.get_by_text("编辑", exact=True)
        if edit.count() == 0:
            raise PageFlowError(f"资质没有编辑入口：{card.qualification_no}")
        edit.first.click(timeout=self.timeout)
        return self._wait_for_qualification_dialog()

    def open_new_qualification(
        self,
        panel: BusinessPanelSnapshot,
        empty_card: QualificationCardSnapshot | None = None,
    ):
        current = self.expand_business(self.find_business(panel.display_name))
        root = self._business_root(current)
        if empty_card is not None:
            cards = self.scan_cards(current)
            empty_cards = [item for item in cards if not item.qualification_no]
            if not empty_cards:
                raise PageFlowError(f"经营业务“{panel.display_name}”的空白资质卡已不存在")
            card_locator = root.locator(f'[data-codex-card-id="{empty_cards[0].dom_id}"]')
            if self._is_inline_qualification_form(card_locator):
                return card_locator
            edit = card_locator.locator('[class*="edit"], .el-icon-edit')
            if edit.count() == 0:
                edit = card_locator.get_by_text("编辑", exact=True)
            if edit.count() == 0:
                # 部分必填空卡本身可点击。
                card_locator.click(timeout=self.timeout)
            else:
                edit.first.click(timeout=self.timeout)
        else:
            upload = root.get_by_text("上传备用资质文件", exact=False)
            if upload.count() == 0:
                raise PageFlowError(f"经营业务“{panel.display_name}”找不到上传备用资质入口")
            upload.last.click(timeout=self.timeout)
        return self._wait_for_qualification_dialog()

    @staticmethod
    def _is_inline_qualification_form(card_locator) -> bool:
        if not card_locator.is_visible():
            return False
        text = re.sub(r"\s+", "", card_locator.inner_text())
        required_labels = ("上传资质文件", "资质编号", "资质名称", "有效期至", "提交")
        return (
            all(label in text for label in required_labels)
            and card_locator.locator("input").count() >= 4
            and card_locator.locator('input[type="file"]').count() >= 1
        )

    def _wait_for_qualification_dialog(self):
        dialog = self.page.locator(".el-dialog:visible").filter(has_text="资质编号").last
        try:
            dialog.wait_for(state="visible", timeout=self.timeout)
        except Exception as exc:
            fallback = self.page.locator('[role="dialog"]:visible').filter(has_text="资质编号").last
            try:
                fallback.wait_for(state="visible", timeout=1_000)
            except Exception:
                raise PageFlowError("打开资质表单后未出现可编辑弹窗") from exc
            dialog = fallback
        return dialog
