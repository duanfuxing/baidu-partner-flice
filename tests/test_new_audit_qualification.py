from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.errors import PageFlowError
from src.models import CompanyInput, Expiry, Qualification, QualificationType
from src.new_audit_qualification import (
    NewAuditQualificationPage,
    evidence_urls_match,
    flatten_qualification_files,
    is_permit_post_response,
    ordered_new_audit_types,
    validate_new_audit_input,
)
from src.workflow import WorkflowRunner


class _Response:
    def __init__(self, status: int, payload=None, error: Exception | None = None) -> None:
        self.status = status
        self._payload = payload
        self._error = error

    def json(self):
        if self._error is not None:
            raise self._error
        return self._payload


@pytest.mark.parametrize(
    ("actual", "expected", "matches"),
    [
        ("https://example.test/path", "https://example.test/path", True),
        ("https://example.test/path", "https://example.test/path#", True),
        ("https://example.test/path#a", "https://example.test/path#b", False),
        ("", "https://example.test/path", False),
        ("https://example.test/other", "https://example.test/path", False),
    ],
)
def test_evidence_urls_match_semantically(
    actual: str, expected: str, matches: bool
) -> None:
    assert evidence_urls_match(actual, expected) is matches


def _qualification(name: str, *files: str) -> Qualification:
    return Qualification(
        index_name=name,
        qualification_no=f"编号-{name}",
        qualification_name=name,
        expiry=Expiry(permanent=False, date=date(2030, 1, 1)),
        evidence_url=f"https://example.test/{name}",
        files=tuple(Path(item) for item in files),
    )


def _company(*types: QualificationType) -> CompanyInput:
    return CompanyInput(
        company_name="示例公司",
        url="https://example.test",
        qualification_types=tuple(types),
        source_path=Path("/tmp/example"),
    )


def test_new_audit_requires_exactly_one_promotion_review_type() -> None:
    missing = _company(
        QualificationType("三类医疗器械", (_qualification("A", "/tmp/a.jpg"),))
    )
    with pytest.raises(PageFlowError, match="恰好存在一个“推广审查”"):
        validate_new_audit_input(missing)

    duplicate = _company(
        QualificationType("推广审查", (_qualification("A", "/tmp/a.jpg"),)),
        QualificationType("推广审查", (_qualification("B", "/tmp/b.jpg"),)),
    )
    with pytest.raises(PageFlowError, match="实际：2"):
        validate_new_audit_input(duplicate)


def test_new_audit_orders_promotion_review_first() -> None:
    company = _company(
        QualificationType("三类医疗器械", (_qualification("A", "/tmp/a.jpg"),)),
        QualificationType("推广审查", (_qualification("B", "/tmp/b.jpg"),)),
        QualificationType("入驻商城类", (_qualification("C", "/tmp/c.jpg"),)),
    )

    assert [item.type_name for item in ordered_new_audit_types(company)] == [
        "推广审查",
        "三类医疗器械",
        "入驻商城类",
    ]


def test_new_audit_rejects_empty_or_over_limit_qualification_directory() -> None:
    empty = _company(
        QualificationType("推广审查", (_qualification("空目录"),)),
    )
    with pytest.raises(PageFlowError, match="空目录.*没有文件"):
        validate_new_audit_input(empty)

    too_many = _company(
        QualificationType(
            "推广审查",
            (_qualification("超限目录", *(f"/tmp/{index}.jpg" for index in range(10))),),
        ),
    )
    with pytest.raises(PageFlowError, match="文件数超过9个"):
        validate_new_audit_input(too_many)


def test_flatten_files_preserves_qualification_then_file_order() -> None:
    qualification_type = QualificationType(
        "推广审查",
        (
            _qualification("A", "/tmp/a1.jpg", "/tmp/a2.jpg"),
            _qualification("B", "/tmp/b1.pdf"),
        ),
    )

    flattened = flatten_qualification_files(qualification_type)

    assert [item.path.name for item in flattened] == ["a1.jpg", "a2.jpg", "b1.pdf"]
    assert [item.qualification.index_name for item in flattened] == ["A", "A", "B"]


def test_submitlice_requires_http_200_and_status_zero() -> None:
    NewAuditQualificationPage._submitlice_response(
        _Response(200, {"status": 0}),
        "a.jpg",
    )

    with pytest.raises(PageFlowError, match="HTTP 500"):
        NewAuditQualificationPage._submitlice_response(
            _Response(500, {"status": 0}),
            "a.jpg",
        )
    with pytest.raises(PageFlowError, match="自动保存失败"):
        NewAuditQualificationPage._submitlice_response(
            _Response(200, {"status": 1, "message": "失败"}),
            "a.jpg",
        )


@pytest.mark.parametrize(
    "response, message",
    [
        (_Response(200, error=ValueError("bad json")), "返回非 JSON"),
        (_Response(200, []), "响应结构异常"),
    ],
)
def test_submitlice_rejects_malformed_payload(response: _Response, message: str) -> None:
    with pytest.raises(PageFlowError, match=message):
        NewAuditQualificationPage._submitlice_response(response, "a.jpg")


@pytest.mark.parametrize(
    "url, method, expected",
    [
        (
            "https://fkzhunru.baidu.com/permit/web/permit/submitlice",
            "POST",
            True,
        ),
        (
            "https://fkzhunru.baidu.com/permit/web/permit/submitlice?draft=1",
            "POST",
            True,
        ),
        (
            "http://fkzhunru.baidu.com/permit/web/permit/submitlice",
            "POST",
            False,
        ),
        (
            "https://example.test/permit/web/permit/submitlice",
            "POST",
            False,
        ),
        (
            "https://fkzhunru.baidu.com/permit/web/permit/submitlice/other",
            "POST",
            False,
        ),
        (
            "https://fkzhunru.baidu.com/permit/web/permit/submitlice",
            "GET",
            False,
        ),
    ],
)
def test_permit_response_matcher_is_bound_to_exact_https_post(
    url: str,
    method: str,
    expected: bool,
) -> None:
    response = SimpleNamespace(url=url, request=SimpleNamespace(method=method))

    assert (
        is_permit_post_response(response, "/permit/web/permit/submitlice")
        is expected
    )


def test_new_audit_accepts_blank_legacy_fields_but_legacy_flow_rejects_them() -> None:
    qualification = Qualification(
        index_name="资质1",
        qualification_no="",
        qualification_name="",
        expiry=Expiry(permanent=False),
        evidence_url=None,
        files=(Path("/tmp/a.jpg"),),
    )
    company = _company(QualificationType("推广审查", (qualification,)))

    validate_new_audit_input(company)
    with pytest.raises(PageFlowError, match="当前为旧版资质页面"):
        WorkflowRunner._validate_legacy_qualification_fields(company)
