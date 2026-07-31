from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from src.models import CompanyInput, Expiry, Qualification, QualificationType
import src.scheduler as scheduler_module
from src.scheduler import ExecutionScheduler, automatic_worker_count


def _company(root: Path, name: str) -> CompanyInput:
    source = root / name
    source.mkdir()
    return CompanyInput(
        company_name=name,
        url=f"https://example.com/{name}",
        qualification_types=(),
        source_path=source,
    )


def _company_with_file(root: Path, name: str) -> tuple[CompanyInput, Path]:
    company = _company(root, name)
    file_path = company.source_path / "资质.jpg"
    file_path.write_bytes(b"version-one")
    qualification = Qualification(
        index_name="资质1",
        qualification_no="编号1",
        qualification_name="名称1",
        expiry=Expiry(permanent=False, date=date(2027, 1, 10)),
        evidence_url=None,
        files=(file_path,),
    )
    return (
        CompanyInput(
            company_name=company.company_name,
            url=company.url,
            qualification_types=(
                QualificationType("推广审查", (qualification,)),
            ),
            source_path=company.source_path,
        ),
        file_path,
    )


def test_worker_count_is_disabled_for_parallel_submission() -> None:
    assert automatic_worker_count(0) == 0
    assert automatic_worker_count(1) == 1
    assert automatic_worker_count(2) == 1
    assert automatic_worker_count(3) == 1


def test_windows_pid_check_never_uses_os_kill(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(scheduler_module.os, "name", "nt")
    monkeypatch.setattr(
        scheduler_module,
        "_windows_pid_is_alive",
        lambda pid: calls.append(pid) or True,
    )
    monkeypatch.setattr(
        scheduler_module.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("不得调用 os.kill")),
    )

    assert scheduler_module._pid_is_alive(1234)
    assert calls == [1234]


def test_scheduler_tracks_queued_running_and_completed_company(tmp_path: Path) -> None:
    first = _company(tmp_path, "公司A")
    second = _company(tmp_path, "公司B")
    scheduler = ExecutionScheduler(tmp_path)

    reserved, busy, completed = scheduler.reserve(
        (first, second),
        run_id="run-one",
        coordinator_pid=os.getpid(),
    )

    assert reserved == (first, second)
    assert busy == ()
    assert completed == ()
    queued = scheduler.snapshot()
    assert queued["queuedCompanies"] == ["公司A", "公司B"]
    assert queued["runningCompanies"] == []

    scheduler.mark_running(first, run_id="run-one", worker_pid=os.getpid())
    running = scheduler.snapshot()
    assert running["runningCompanies"] == ["公司A"]
    assert running["queuedCompanies"] == ["公司B"]

    scheduler.mark_completed(
        first,
        run_id="run-one",
        success=True,
        result_path=str(first.source_path / "qualification-submit-result.json"),
    )
    completed = scheduler.snapshot()
    assert completed["companies"]["公司A"]["status"] == "success"
    assert completed["runningCompanies"] == []
    company_status = json.loads(
        (first.source_path / "execution-status.json").read_text(encoding="utf-8")
    )
    assert company_status["status"] == "success"


def test_scheduler_persists_error_code(tmp_path: Path) -> None:
    company = _company(tmp_path, "公司A")
    scheduler = ExecutionScheduler(tmp_path)
    scheduler.reserve(
        (company,),
        run_id="failed-run",
        coordinator_pid=os.getpid(),
    )
    scheduler.mark_running(
        company,
        run_id="failed-run",
        worker_pid=os.getpid(),
    )

    scheduler.mark_completed(
        company,
        run_id="failed-run",
        success=False,
        error="用户取消任务",
        error_code="task-cancelled",
    )

    status = json.loads(
        (company.source_path / "execution-status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert status["errorCode"] == "task-cancelled"
    assert scheduler.snapshot()["companies"]["公司A"]["errorCode"] == (
        "task-cancelled"
    )


def test_scheduler_prevents_two_runs_from_claiming_same_company(tmp_path: Path) -> None:
    company = _company(tmp_path, "公司A")
    scheduler = ExecutionScheduler(tmp_path)
    scheduler.reserve(
        (company,),
        run_id="run-one",
        coordinator_pid=os.getpid(),
    )

    reserved, busy, completed = scheduler.reserve(
        (company,),
        run_id="run-two",
        coordinator_pid=os.getpid(),
    )

    assert reserved == ()
    assert busy[0]["companyName"] == "公司A"
    assert busy[0]["runId"] == "run-one"
    assert completed == ()


def test_scheduler_reclaims_stale_queued_company(tmp_path: Path) -> None:
    company = _company(tmp_path, "公司A")
    scheduler = ExecutionScheduler(tmp_path)
    scheduler.reserve(
        (company,),
        run_id="stale-run",
        coordinator_pid=99_999_999,
    )

    reserved, busy, completed = scheduler.reserve(
        (company,),
        run_id="new-run",
        coordinator_pid=os.getpid(),
    )

    assert reserved == (company,)
    assert busy == ()
    assert completed == ()
    assert scheduler.snapshot()["companies"]["公司A"]["runId"] == "new-run"


def test_scheduler_skips_same_input_after_success(tmp_path: Path) -> None:
    company = _company(tmp_path, "公司A")
    scheduler = ExecutionScheduler(tmp_path)
    scheduler.reserve(
        (company,),
        run_id="first-run",
        coordinator_pid=os.getpid(),
    )
    scheduler.mark_running(
        company,
        run_id="first-run",
        worker_pid=os.getpid(),
    )
    scheduler.mark_completed(
        company,
        run_id="first-run",
        success=True,
        result_path=str(company.source_path / "qualification-submit-result.json"),
    )

    reserved, busy, completed = scheduler.reserve(
        (company,),
        run_id="second-run",
        coordinator_pid=os.getpid(),
    )

    assert reserved == ()
    assert busy == ()
    assert completed[0]["companyName"] == "公司A"


def test_dry_run_does_not_skip_previously_completed_company(tmp_path: Path) -> None:
    company = _company(tmp_path, "公司A")
    scheduler = ExecutionScheduler(tmp_path)
    scheduler.reserve(
        (company,),
        run_id="first-run",
        coordinator_pid=os.getpid(),
    )
    scheduler.mark_running(
        company,
        run_id="first-run",
        worker_pid=os.getpid(),
    )
    scheduler.mark_completed(company, run_id="first-run", success=True)

    reserved, busy, completed = scheduler.reserve(
        (company,),
        run_id="dry-run",
        coordinator_pid=os.getpid(),
        dry_run=True,
    )

    assert reserved == (company,)
    assert busy == ()
    assert completed == ()


def test_run_without_final_submit_can_be_scheduled_again(tmp_path: Path) -> None:
    company = _company(tmp_path, "公司A")
    scheduler = ExecutionScheduler(tmp_path)
    scheduler.reserve(
        (company,),
        run_id="fill-only-run",
        coordinator_pid=os.getpid(),
        final_submit=False,
    )
    scheduler.mark_running(
        company,
        run_id="fill-only-run",
        worker_pid=os.getpid(),
    )
    scheduler.mark_completed(company, run_id="fill-only-run", success=True)

    reserved, busy, completed = scheduler.reserve(
        (company,),
        run_id="final-submit-run",
        coordinator_pid=os.getpid(),
        final_submit=True,
    )

    assert reserved == (company,)
    assert busy == ()
    assert completed == ()
    assert scheduler.snapshot()["companies"]["公司A"]["finalSubmit"] is True


def test_final_result_prevents_reopening_locked_company_even_in_dry_run(
    tmp_path: Path,
) -> None:
    company = _company(tmp_path, "公司A")
    (company.source_path / "qualification-submit-result.json").write_text(
        json.dumps(
            {
                "success": True,
                "final_submission_success": True,
                "qualifications": [],
            }
        ),
        encoding="utf-8",
    )
    scheduler = ExecutionScheduler(tmp_path)

    reserved, busy, completed = scheduler.reserve(
        (company,),
        run_id="dry-run",
        coordinator_pid=os.getpid(),
        dry_run=True,
    )

    assert reserved == ()
    assert busy == ()
    assert completed[0]["companyName"] == "公司A"


def test_changed_input_file_is_scheduled_again_after_previous_success(
    tmp_path: Path,
) -> None:
    company, file_path = _company_with_file(tmp_path, "公司A")
    scheduler = ExecutionScheduler(tmp_path)
    scheduler.reserve(
        (company,),
        run_id="first-run",
        coordinator_pid=os.getpid(),
    )
    scheduler.mark_running(company, run_id="first-run", worker_pid=os.getpid())
    scheduler.mark_completed(company, run_id="first-run", success=True)
    file_path.write_bytes(b"version-two")

    reserved, busy, completed = scheduler.reserve(
        (company,),
        run_id="second-run",
        coordinator_pid=os.getpid(),
    )

    assert reserved == (company,)
    assert busy == ()
    assert completed == ()
