from __future__ import annotations

import os
from pathlib import Path

import pytest

import src.application as application_module
from src.application import (
    ValidationReport,
    is_run_successful,
    run_validated_companies,
    validate_input_directory,
)
from src.browser import BrowserConfig
from src.errors import TaskCancelled
from src.models import CompanyInput
from src.scheduler import ExecutionScheduler
from src.workflow import WorkflowConfig


def _write_qualification(root: Path, type_name: str, name: str, file_count: int) -> None:
    directory = root / type_name / name
    directory.mkdir(parents=True)
    (directory / "表单信息.txt").write_text(
        "资质编号：编号1\n"
        f"资质名称：{name}\n"
        "有效期至：永久\n"
        "举证链接：\n",
        encoding="utf-8",
    )
    for index in range(file_count):
        (directory / f"{index + 1}.jpg").write_bytes(b"image")


def test_validation_report_summarizes_display_data(tmp_path: Path) -> None:
    first = tmp_path / "公司A"
    first.mkdir()
    (first / "url.txt").write_text("https:/example.com/a\n", encoding="utf-8")
    _write_qualification(first, "类型A", "资质A", 2)
    _write_qualification(first, "类型A", "资质B", 1)

    second = tmp_path / "公司B"
    second.mkdir()
    (second / "url.txt").write_text("https://example.com/b", encoding="utf-8")
    _write_qualification(second, "类型B", "资质C", 1)

    report = validate_input_directory(tmp_path)

    assert report.company_count == 2
    assert report.qualification_type_count == 2
    assert report.qualification_count == 3
    assert report.file_count == 4
    assert report.companies[0].url == "https://example.com/a"
    assert all(path.name == "input.json" for path in report.saved_paths)


def test_validation_report_uses_resolved_selected_directory(tmp_path: Path) -> None:
    company = tmp_path / "公司A"
    company.mkdir()
    (company / "url.txt").write_text("https://example.com/a", encoding="utf-8")
    _write_qualification(company, "类型A", "资质A", 1)

    report = validate_input_directory(tmp_path)

    assert report.input_root == tmp_path.resolve()


def test_busy_companies_are_not_a_successful_run() -> None:
    assert is_run_successful({"failures": [], "busy": []})
    assert not is_run_successful({"failures": [], "busy": [{"companyName": "公司A"}]})
    assert not is_run_successful({"failures": [{"companyName": "公司A"}], "busy": []})


def test_cancellation_waits_for_current_company_and_marks_remaining(
    tmp_path: Path,
    monkeypatch,
) -> None:
    companies = tuple(
        CompanyInput(
            company_name=name,
            url=f"https://example.com/{name}",
            qualification_types=(),
            source_path=tmp_path / name,
        )
        for name in ("公司A", "公司B")
    )
    for company in companies:
        company.source_path.mkdir()
    report = ValidationReport(tmp_path, companies, ())

    class FakeBrowserSession:
        def __init__(self, _config) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def ensure_logged_in(self, prompt):
            return None

    class ImmediateFuture:
        def __init__(self, result) -> None:
            self._result = result

        def result(self):
            return self._result

    class ImmediateExecutor:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def submit(self, function, *args, **kwargs):
            return ImmediateFuture(function(*args, **kwargs))

    def fake_worker(company, **kwargs):
        scheduler = ExecutionScheduler(kwargs["input_root"])
        scheduler.mark_running(
            company,
            run_id=kwargs["run_id"],
            worker_pid=os.getpid(),
        )
        scheduler.mark_completed(
            company,
            run_id=kwargs["run_id"],
            success=True,
        )
        return {
            "success": True,
            "companyName": company.company_name,
            "result": {"company_name": company.company_name},
        }

    cancellation_checks = iter((False, False, False, True))
    monkeypatch.setattr(application_module, "BrowserSession", FakeBrowserSession)
    monkeypatch.setattr(
        application_module.concurrent.futures,
        "ProcessPoolExecutor",
        ImmediateExecutor,
    )
    monkeypatch.setattr(application_module, "run_company_worker", fake_worker)

    with pytest.raises(TaskCancelled, match="后续未开始公司"):
        run_validated_companies(
            report,
            browser_config=BrowserConfig(),
            workflow_config=WorkflowConfig(),
            login_prompt=lambda _message: "",
            is_cancelled=lambda: next(cancellation_checks),
        )

    first_status = ExecutionScheduler(tmp_path).snapshot()["companies"]
    assert first_status["公司A"]["status"] == "success"
    assert first_status["公司B"]["status"] == "failed"
    assert first_status["公司B"]["errorCode"] == "task-cancelled"
