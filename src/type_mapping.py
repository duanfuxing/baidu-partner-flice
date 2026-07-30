"""经营业务名称规范化和显式映射。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import PageFlowError


@dataclass(frozen=True)
class BusinessTypeMapping:
    input_name: str
    page_names: tuple[str, ...]
    mandatory: bool = False

    @property
    def canonical_page_name(self) -> str:
        return self.page_names[0]


BUSINESS_TYPE_MAPPINGS: tuple[BusinessTypeMapping, ...] = (
    BusinessTypeMapping("推广审查", ("推广审查",), mandatory=True),
    BusinessTypeMapping("一类医疗器械", ("一类医疗器械（不可个人，B）", "一类医疗器械(不可个人,B)")),
    BusinessTypeMapping("二类医疗器械", ("二类医疗器械（不可个人，B）", "二类医疗器械(不可个人,B)")),
    BusinessTypeMapping("三类医疗器械", ("三类医疗器械（不可个人，B）", "三类医疗器械(不可个人,B)")),
    BusinessTypeMapping(
        "电商代运营",
        (
            "电商代运营【房产承诺函传营业执照（如未要求提交承诺函请忽略）】",
            "电商代运营[房产承诺函传营业执照(如未要求提交承诺函请忽略)]",
        ),
    ),
    BusinessTypeMapping("入驻商城类", ("入驻商城类（不可个人，C2）", "入驻商城类(不可个人,C2)")),
)


def normalize_business_name(value: str) -> str:
    """去除动态序号和纯展示差异，保留业务语义。"""

    normalized = value.replace("\u3000", " ").strip()
    normalized = re.sub(r"^经营业务\s*\d+\s*[：:]\s*", "", normalized)
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("【", "[").replace("】", "]")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("，", ",")
    normalized = re.sub(
        r"(待审核|审核中|已审核|审核通过|已通过|通过|被拒绝|已拒绝|拒绝|待提交)$",
        "",
        normalized,
    )
    return normalized


_BY_INPUT = {item.input_name: item for item in BUSINESS_TYPE_MAPPINGS}
_BY_PAGE: dict[str, BusinessTypeMapping] = {}
for _mapping in BUSINESS_TYPE_MAPPINGS:
    for _page_name in _mapping.page_names:
        _normalized = normalize_business_name(_page_name)
        if _normalized in _BY_PAGE and _BY_PAGE[_normalized] != _mapping:
            raise RuntimeError(f"经营业务映射冲突：{_page_name}")
        _BY_PAGE[_normalized] = _mapping


def mapping_for_input(input_name: str) -> BusinessTypeMapping:
    try:
        return _BY_INPUT[input_name.strip()]
    except KeyError as exc:
        raise PageFlowError(f"未配置经营业务类型映射：{input_name}") from exc


def mapping_for_page(page_name: str) -> BusinessTypeMapping | None:
    return _BY_PAGE.get(normalize_business_name(page_name))


def page_name_matches(mapping: BusinessTypeMapping, page_name: str) -> bool:
    normalized = normalize_business_name(page_name)
    return any(normalized == normalize_business_name(alias) for alias in mapping.page_names)
