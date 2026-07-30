"""单 worker 串行执行时的跨进程 JSON 调度状态。"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import portalocker

from .errors import SchedulerError
from .models import CompanyInput

MAX_WORKERS = 1
SCHEDULER_FILENAME = "scheduler.json"
LOCK_FILENAME = ".scheduler.lock"
COMPANY_STATUS_FILENAME = "execution-status.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def automatic_worker_count(company_count: int) -> int:
    return min(MAX_WORKERS, max(0, company_count))


def company_input_fingerprint(company: CompanyInput) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            company.to_dict(relative_to=company.source_path),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    for qualification_type in company.qualification_types:
        for qualification in qualification_type.qualifications:
            for path in qualification.files:
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
    return digest.hexdigest()


def _completed_result_matches(company: CompanyInput) -> bool:
    path = company.source_path / "qualification-submit-result.json"
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not payload.get("success") or not payload.get("final_submission_success"):
        return False
    history = {
        (
            item.get("type_name"),
            item.get("qualification_no"),
            item.get("qualification_name"),
        ): tuple(item.get("input_file_hashes") or ())
        for item in payload.get("qualifications") or ()
        if item.get("success")
    }
    expected_keys: set[tuple[str, str, str]] = set()
    for qualification_type in company.qualification_types:
        for qualification in qualification_type.qualifications:
            key = (
                qualification_type.type_name,
                qualification.qualification_no,
                qualification.qualification_name,
            )
            expected_keys.add(key)
            hashes: list[str] = []
            for file_path in qualification.files:
                digest = hashlib.sha256()
                with file_path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                hashes.append(digest.hexdigest())
            if history.get(key) != tuple(hashes):
                return False
    return set(history) == expected_keys


def _pid_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    """通过 Win32 等待 API 无损检查进程，绝不向目标发送信号。"""

    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    wait_object_0 = 0x00000000
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(synchronize, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return False
        # 权限不足或其他未知错误时按存活处理，避免错误回收导致重复提交。
        return True
    try:
        wait_result = wait_for_single_object(handle, 0)
        if wait_result == wait_timeout:
            return True
        if wait_result == wait_object_0:
            return False
        # 未知等待结果同样按存活处理，安全优先。
        return True
    finally:
        close_handle(handle)


class ExecutionScheduler:
    def __init__(self, input_root: Path | str) -> None:
        self.input_root = Path(input_root).expanduser().resolve()
        self.path = self.input_root / SCHEDULER_FILENAME
        self.lock_path = self.input_root / LOCK_FILENAME

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            self.input_root.mkdir(parents=True, exist_ok=True)
            with portalocker.Lock(
                str(self.lock_path),
                mode="a+",
                timeout=60,
                encoding="utf-8",
            ):
                yield
        except (OSError, portalocker.exceptions.LockException) as exc:
            raise SchedulerError(f"调度锁操作失败：{self.lock_path}：{exc}") from exc

    def _load_unlocked(self) -> dict:
        if not self.path.is_file():
            return {
                "version": 1,
                "maxWorkers": MAX_WORKERS,
                "updatedAt": _now(),
                "runningCompanies": [],
                "queuedCompanies": [],
                "companies": {},
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise SchedulerError(f"调度文件损坏或无法读取：{self.path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("companies"), dict):
            raise SchedulerError(f"调度文件结构无效：{self.path}")
        return payload

    def _save_unlocked(self, payload: dict) -> None:
        payload["version"] = 1
        payload["maxWorkers"] = MAX_WORKERS
        payload["updatedAt"] = _now()
        companies = payload.get("companies") or {}
        payload["runningCompanies"] = sorted(
            name
            for name, item in companies.items()
            if item.get("status") == "running"
        )
        payload["queuedCompanies"] = sorted(
            name
            for name, item in companies.items()
            if item.get("status") == "queued"
        )
        temporary = self.input_root / f".{SCHEDULER_FILENAME}.{os.getpid()}.tmp"
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            raise SchedulerError(f"调度文件保存失败：{self.path}：{exc}") from exc

    @staticmethod
    def _entry_is_active(entry: dict) -> bool:
        status = entry.get("status")
        if status == "running":
            return _pid_is_alive(entry.get("workerPid"))
        if status == "queued":
            return _pid_is_alive(entry.get("coordinatorPid"))
        return False

    def _write_company_status_unlocked(self, company: CompanyInput, entry: dict) -> None:
        target = company.source_path / COMPANY_STATUS_FILENAME
        temporary = company.source_path / f".{COMPANY_STATUS_FILENAME}.{os.getpid()}.tmp"
        try:
            temporary.write_text(
                json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
        except OSError as exc:
            raise SchedulerError(f"公司状态保存失败：{target}：{exc}") from exc

    def reserve(
        self,
        companies: tuple[CompanyInput, ...],
        *,
        run_id: str,
        coordinator_pid: int,
        dry_run: bool = False,
        final_submit: bool = True,
    ) -> tuple[tuple[CompanyInput, ...], tuple[dict, ...], tuple[dict, ...]]:
        """原子预留公司；其他仍存活进程持有的公司不会被重复领取。"""

        reserved: list[CompanyInput] = []
        busy: list[dict] = []
        completed: list[dict] = []
        with self._locked():
            payload = self._load_unlocked()
            entries = payload.setdefault("companies", {})
            for company in companies:
                previous = entries.get(company.company_name) or {}
                if self._entry_is_active(previous):
                    busy.append(
                        {
                            "companyName": company.company_name,
                            "status": previous.get("status"),
                            "runId": previous.get("runId"),
                            "workerPid": previous.get("workerPid"),
                        }
                    )
                    continue
                fingerprint = company_input_fingerprint(company)
                already_completed = (
                    _completed_result_matches(company)
                    or (
                        not dry_run
                        and previous.get("status") == "success"
                        and previous.get("inputFingerprint") == fingerprint
                        and not previous.get("dryRun")
                        and previous.get("finalSubmit", True)
                    )
                )
                if already_completed:
                    entry = {
                        **previous,
                        "companyName": company.company_name,
                        "sourcePath": str(company.source_path),
                        "status": "success",
                        "runId": previous.get("runId") or run_id,
                        "coordinatorPid": None,
                        "workerPid": None,
                        "inputFingerprint": fingerprint,
                        "dryRun": False,
                        "finalSubmit": True,
                        "completedAt": previous.get("completedAt") or _now(),
                        "resultPath": str(
                            company.source_path / "qualification-submit-result.json"
                        ),
                        "error": None,
                    }
                    entries[company.company_name] = entry
                    self._write_company_status_unlocked(company, entry)
                    completed.append(
                        {
                            "companyName": company.company_name,
                            "status": "success",
                            "resultPath": entry["resultPath"],
                        }
                    )
                    continue
                entry = {
                    "companyName": company.company_name,
                    "sourcePath": str(company.source_path),
                    "status": "queued",
                    "runId": run_id,
                    "coordinatorPid": coordinator_pid,
                    "workerPid": None,
                    "inputFingerprint": fingerprint,
                    "dryRun": dry_run,
                    "finalSubmit": final_submit,
                    "queuedAt": _now(),
                    "startedAt": None,
                    "completedAt": None,
                    "resultPath": None,
                    "error": None,
                }
                entries[company.company_name] = entry
                self._write_company_status_unlocked(company, entry)
                reserved.append(company)
            self._save_unlocked(payload)
        return tuple(reserved), tuple(busy), tuple(completed)

    def mark_running(
        self,
        company: CompanyInput,
        *,
        run_id: str,
        worker_pid: int,
    ) -> None:
        with self._locked():
            payload = self._load_unlocked()
            entry = (payload.get("companies") or {}).get(company.company_name)
            if not entry or entry.get("runId") != run_id or entry.get("status") != "queued":
                raise SchedulerError(f"公司调度预留已失效：{company.company_name}")
            entry.update(
                {
                    "status": "running",
                    "workerPid": worker_pid,
                    "startedAt": _now(),
                    "completedAt": None,
                    "error": None,
                }
            )
            self._write_company_status_unlocked(company, entry)
            self._save_unlocked(payload)

    def mark_completed(
        self,
        company: CompanyInput,
        *,
        run_id: str,
        success: bool,
        result_path: str | None = None,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        with self._locked():
            payload = self._load_unlocked()
            entry = (payload.get("companies") or {}).get(company.company_name)
            if not entry or entry.get("runId") != run_id:
                raise SchedulerError(f"公司调度状态不属于当前任务：{company.company_name}")
            entry.update(
                {
                    "status": (
                        "dry-run-success"
                        if success and entry.get("dryRun")
                        else "success" if success else "failed"
                    ),
                    "completedAt": _now(),
                    "resultPath": result_path,
                    "error": error,
                    "errorCode": error_code,
                }
            )
            self._write_company_status_unlocked(company, entry)
            self._save_unlocked(payload)

    def snapshot(self) -> dict:
        with self._locked():
            return self._load_unlocked()
