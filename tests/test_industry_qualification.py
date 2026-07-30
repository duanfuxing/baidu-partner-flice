from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.errors import PageFlowError
from src.industry_qualification import (
    BusinessPanelSnapshot,
    QualificationCardSnapshot,
    build_execution_plan,
    validate_unique_input_qualification_keys,
)
from src.models import CompanyInput, Expiry, Qualification, QualificationType
from src.qualification_form import qualification_matches
from src.submission_result import QualificationActionResult, SubmissionResult
from src.type_mapping import (
    mapping_for_input,
    mapping_for_page,
    normalize_business_name,
)
from src.workflow import WorkflowRunner


def _qualification(
    number: str,
    *,
    name: str = "示例资质",
    permanent: bool = False,
    evidence_url: str | None = None,
    file_count: int = 1,
) -> Qualification:
    expiry = Expiry(permanent=True) if permanent else Expiry(permanent=False, date=date(2027, 1, 10))
    return Qualification(
        index_name=number,
        qualification_no=number,
        qualification_name=name,
        expiry=expiry,
        evidence_url=evidence_url,
        files=tuple(Path(f"/tmp/{index}.jpg") for index in range(file_count)),
    )


def _company(*types: QualificationType) -> CompanyInput:
    return CompanyInput(
        company_name="示例公司",
        url="https://example.com",
        qualification_types=tuple(types),
        source_path=Path("/tmp/example"),
    )


def _panel(name: str, *, deletable: bool = True, index: int = 1) -> BusinessPanelSnapshot:
    return BusinessPanelSnapshot(
        dom_id=f"panel-{index}",
        header_text=f"经营业务{index}：{name}",
        display_name=name,
        deletable=deletable,
        expanded=False,
    )


def test_normalize_business_name_removes_dynamic_prefix_and_display_spacing() -> None:
    assert normalize_business_name("经营业务2： 二类医疗器械 （不可个人， B）") == (
        "二类医疗器械(不可个人,B)"
    )


def test_normalize_business_name_removes_final_submission_status() -> None:
    assert normalize_business_name("经营业务3：推广审查 待审核") == "推广审查"
    assert normalize_business_name("二类医疗器械（不可个人，B） 审核中") == (
        "二类医疗器械(不可个人,B)"
    )


def test_one_class_medical_device_is_not_mall_business() -> None:
    one_class = mapping_for_input("一类医疗器械")

    assert one_class.canonical_page_name == "一类医疗器械（不可个人，B）"
    assert mapping_for_page("入驻商城类（不可个人，C2）").input_name == "入驻商城类"


def test_build_execution_plan_splits_existing_delete_and_add_types() -> None:
    company = _company(
        QualificationType("推广审查", (_qualification("A"),)),
        QualificationType("一类医疗器械", (_qualification("B"),)),
        QualificationType("二类医疗器械", (_qualification("C"),)),
    )
    panels = (
        _panel("推广审查", deletable=False, index=1),
        _panel("二类医疗器械（不可个人，B）", index=2),
        _panel("三类医疗器械（不可个人，B）", index=3),
    )

    plan = build_execution_plan(company, panels)

    assert [item[0].type_name for item in plan.existing_types] == ["推广审查", "二类医疗器械"]
    assert [item.display_name for item in plan.delete_businesses] == [
        "三类医疗器械（不可个人，B）"
    ]
    assert [item[0].type_name for item in plan.add_types] == ["一类医疗器械"]
    assert [item.display_name for item in plan.mandatory_businesses] == ["推广审查"]


def test_build_execution_plan_rejects_unknown_page_business() -> None:
    company = _company(QualificationType("推广审查", (_qualification("A"),)))

    with pytest.raises(PageFlowError, match="未配置的经营业务"):
        build_execution_plan(company, (_panel("未知业务"),))


def test_duplicate_input_number_with_different_names_is_allowed() -> None:
    company = _company(
        QualificationType(
            "二类医疗器械",
            (
                _qualification("重复编号", name="资质一"),
                _qualification("重复编号", name="资质二"),
            ),
        )
    )

    validate_unique_input_qualification_keys(company)


def test_duplicate_input_number_and_name_is_rejected_before_page_changes() -> None:
    company = _company(
        QualificationType(
            "二类医疗器械",
            (
                _qualification("重复编号", name="相同名称"),
                _qualification("重复编号", name="相同名称"),
            ),
        )
    )

    with pytest.raises(PageFlowError, match="资质编号 \\+ 资质名称"):
        validate_unique_input_qualification_keys(company)


def test_qualification_matches_all_visible_fields_and_file_count() -> None:
    qualification = _qualification(
        "编号1",
        name="资质名称",
        evidence_url="https://example.com/evidence",
        file_count=2,
    )
    card = QualificationCardSnapshot(
        dom_id="card-1",
        qualification_no="编号1",
        qualification_name="资质名称",
        expiry_text="2027-01-10",
        evidence_url="https://example.com/evidence",
        status="待提交",
        deletable=True,
        file_count=2,
        file_identifiers=("server-0.jpg", "server-1.jpg"),
    )

    assert qualification_matches(
        card,
        qualification,
        ("server-0.jpg", "server-1.jpg"),
    )
    assert not qualification_matches(card, qualification)
    assert not qualification_matches(
        QualificationCardSnapshot(**{**card.__dict__, "file_count": 1}),
        qualification,
        ("server-0.jpg", "server-1.jpg"),
    )


def test_submission_history_requires_uploaded_ids_and_input_hashes(
    tmp_path: Path,
) -> None:
    result = SubmissionResult(company_name="示例公司", url="https://example.com")
    result.qualifications.append(
        QualificationActionResult(
            type_name="推广审查",
            qualification_no="编号1",
            qualification_name="名称1",
            action="created",
            success=True,
            file_count=1,
            uploaded_file_ids=("server-1.jpg",),
            input_file_hashes=("sha256-value",),
        )
    )
    result.finish()
    result.save(tmp_path)

    history = SubmissionResult.load_file_history(tmp_path)

    assert history[("推广审查", "编号1", "名称1")] == (
        ("server-1.jpg",),
        ("sha256-value",),
    )


def test_overwrite_plan_retains_first_non_deletable_card_and_deletes_all_others() -> None:
    first = QualificationCardSnapshot(
        "card-first", "旧编号1", "旧名称1", "2027-01-10", None, "待提交", False, 1
    )
    matching_but_deletable = QualificationCardSnapshot(
        "card-second", "目标编号", "目标名称", "2027-01-10", None, "待提交", True, 1
    )
    other = QualificationCardSnapshot(
        "card-third", "旧编号3", "旧名称3", "2027-01-10", None, "待提交", True, 1
    )

    retained, deleted = WorkflowRunner._overwrite_card_plan(
        (first, matching_but_deletable, other)
    )

    assert retained == first
    assert deleted == (matching_but_deletable, other)


def test_overwrite_plan_deletes_every_filled_card_when_all_are_deletable() -> None:
    cards = (
        QualificationCardSnapshot(
            "card-a", "编号A", "名称A", "2027-01-10", None, "待提交", True, 1
        ),
        QualificationCardSnapshot(
            "card-b", "编号B", "名称B", "2027-01-10", None, "待提交", True, 1
        ),
    )

    retained, deleted = WorkflowRunner._overwrite_card_plan(cards)

    assert retained is None
    assert deleted == cards


def test_overwrite_plan_rejects_multiple_non_deletable_filled_cards() -> None:
    cards = (
        QualificationCardSnapshot(
            "card-a", "编号A", "名称A", "2027-01-10", None, "待提交", False, 1
        ),
        QualificationCardSnapshot(
            "card-b", "编号B", "名称B", "2027-01-10", None, "待提交", False, 1
        ),
    )

    with pytest.raises(PageFlowError, match="多个不可删除"):
        WorkflowRunner._overwrite_card_plan(cards)
