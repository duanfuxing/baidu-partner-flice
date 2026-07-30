from __future__ import annotations

import pytest

import src.workflow as workflow_module
from src.errors import PageFlowError
from src.submission_result import QualificationActionResult, SubmissionResult
from src.workflow import WorkflowConfig, complete_final_submission


def _result(*, qualification_success: bool = True) -> SubmissionResult:
    result = SubmissionResult(
        company_name="示例公司",
        url="https://example.com",
    )
    result.qualifications.append(
        QualificationActionResult(
            type_name="推广审查",
            qualification_no="编号1",
            qualification_name="名称1",
            action="replace",
            success=qualification_success,
        )
    )
    return result


def test_final_submit_option_clicks_submit_all(monkeypatch) -> None:
    calls: list[tuple[object, int]] = []
    monkeypatch.setattr(
        workflow_module,
        "submit_all_qualifications",
        lambda page, timeout: calls.append((page, timeout)),
    )
    page = object()
    result = _result()

    completed = complete_final_submission(
        page,
        result,
        WorkflowConfig(page_timeout_ms=1_234, final_submit=True),
    )

    assert completed is True
    assert result.final_submission_success is True
    assert calls == [(page, 1_234)]


def test_disabled_final_submit_skips_submit_all(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_module,
        "submit_all_qualifications",
        lambda *_args, **_kwargs: pytest.fail("不应调用全部提交"),
    )
    result = _result()

    completed = complete_final_submission(
        object(),
        result,
        WorkflowConfig(final_submit=False),
    )

    assert completed is False
    assert result.qualifications_success is True
    assert result.final_submission_success is False
    assert result.success is False


def test_failed_qualification_never_reaches_submit_all(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_module,
        "submit_all_qualifications",
        lambda *_args, **_kwargs: pytest.fail("不应调用全部提交"),
    )

    with pytest.raises(PageFlowError, match="编号1"):
        complete_final_submission(
            object(),
            _result(qualification_success=False),
            WorkflowConfig(final_submit=True),
        )
