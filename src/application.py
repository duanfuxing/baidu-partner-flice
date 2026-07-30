"""输入校验和自动化执行的应用服务。"""

from __future__ import annotations

import concurrent.futures
import logging
import multiprocessing
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .browser import BrowserConfig, BrowserSession
from .errors import TaskCancelled
from .input_loader import load_input, save_input_json
from .models import CompanyInput
from .scheduler import ExecutionScheduler, automatic_worker_count
from .worker import run_company_worker
from .workflow import WorkflowConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationReport:
    input_root: Path
    companies: tuple[CompanyInput, ...]
    saved_paths: tuple[Path, ...]

    @property
    def company_count(self) -> int:
        return len(self.companies)

    @property
    def qualification_type_count(self) -> int:
        return sum(len(company.qualification_types) for company in self.companies)

    @property
    def qualification_count(self) -> int:
        return sum(
            len(qualification_type.qualifications)
            for company in self.companies
            for qualification_type in company.qualification_types
        )

    @property
    def file_count(self) -> int:
        return sum(
            len(qualification.files)
            for company in self.companies
            for qualification_type in company.qualification_types
            for qualification in qualification_type.qualifications
        )


def is_run_successful(result: dict) -> bool:
    return not result.get("failures") and not result.get("busy")


def validate_input_directory(input_root: Path | str) -> ValidationReport:
    """校验整个输入目录，全部通过后持久化标准化 input.json。"""

    root = Path(input_root).expanduser().resolve()
    companies = load_input(root)
    saved_paths = save_input_json(companies)
    return ValidationReport(root, companies, saved_paths)


def run_validated_companies(
    report: ValidationReport,
    *,
    browser_config: BrowserConfig,
    workflow_config: WorkflowConfig,
    login_prompt: Callable[[str], str],
    log_level: str = "INFO",
    log_file: Path | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    """登录一次后，以固定单 worker 顺序处理校验通过的公司。"""

    companies = report.companies
    input_root = report.input_root
    successes: list[dict] = []
    failures: list[dict] = []
    busy: list[dict] = []
    completed: list[dict] = []

    if is_cancelled is not None and is_cancelled():
        raise TaskCancelled("任务已取消")
    LOGGER.info("输入校验通过，已生成 %d 个 input.json；开始打开 Chrome", len(report.saved_paths))
    with BrowserSession(browser_config) as session:
        session.ensure_logged_in(prompt=login_prompt)
    LOGGER.info("登录状态已确认并保存，登录 Chrome 已关闭")
    if is_cancelled is not None and is_cancelled():
        raise TaskCancelled("任务已取消")

    run_id = uuid.uuid4().hex
    scheduler = ExecutionScheduler(input_root)
    reserved, busy_items, completed_items = scheduler.reserve(
        companies,
        run_id=run_id,
        coordinator_pid=os.getpid(),
        dry_run=workflow_config.dry_run,
        final_submit=workflow_config.final_submit,
    )
    busy.extend(busy_items)
    completed.extend(completed_items)
    for item in completed:
        LOGGER.info("公司相同输入已完成最终提交，跳过重复处理：%s", item["companyName"])
    for item in busy:
        LOGGER.warning("公司正在由其他任务处理，跳过本次领取：%s", item["companyName"])

    worker_count = automatic_worker_count(len(reserved))
    if worker_count:
        LOGGER.info("调度 %d 个公司，使用单 worker 串行处理", len(reserved))
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=context,
        ) as executor:
            for index, company in enumerate(reserved):
                if is_cancelled is not None and is_cancelled():
                    _mark_companies_cancelled(
                        scheduler,
                        reserved[index:],
                        run_id=run_id,
                    )
                    raise TaskCancelled("任务已安全取消，未开始的公司已标记为取消")
                future = executor.submit(
                    run_company_worker,
                    company,
                    input_root=str(input_root),
                    run_id=run_id,
                    browser_config=browser_config,
                    workflow_config=workflow_config,
                    log_level=log_level,
                    log_file=str(log_file) if log_file else None,
                )
                try:
                    worker_result = future.result()
                except Exception as exc:
                    error = f"worker 进程异常退出：{exc}"
                    scheduler.mark_completed(
                        company,
                        run_id=run_id,
                        success=False,
                        error=error,
                    )
                    failures.append({"companyName": company.company_name, "error": error})
                else:
                    if worker_result["success"]:
                        successes.append(worker_result["result"])
                    else:
                        failures.append(
                            {
                                "companyName": worker_result["companyName"],
                                "error": worker_result["error"],
                                "errorCode": worker_result.get("errorCode"),
                            }
                        )
                if is_cancelled is not None and is_cancelled() and index + 1 < len(reserved):
                    _mark_companies_cancelled(
                        scheduler,
                        reserved[index + 1 :],
                        run_id=run_id,
                    )
                    raise TaskCancelled(
                        "当前公司已稳定结束，后续未开始公司已标记为取消"
                    )

    for failure in failures:
        LOGGER.error("公司处理失败：%s：%s", failure["companyName"], failure["error"])
    if not failures and not busy:
        LOGGER.info("全部公司处理完成，所有 Chrome 已关闭")
    elif busy and not failures:
        LOGGER.info("本次领取的公司均处理完成；被占用公司由其他任务继续执行")

    company_order = {
        company.company_name: index
        for index, company in enumerate(companies)
    }
    for items in (successes, failures, busy, completed):
        items.sort(
            key=lambda item: company_order.get(
                item.get("company_name") or item.get("companyName", ""),
                len(companies),
            )
        )
    return {
        "successes": successes,
        "failures": failures,
        "busy": busy,
        "completed": completed,
        "scheduler": str(input_root / "scheduler.json"),
    }


def _mark_companies_cancelled(
    scheduler: ExecutionScheduler,
    companies: tuple[CompanyInput, ...],
    *,
    run_id: str,
) -> None:
    for company in companies:
        scheduler.mark_completed(
            company,
            run_id=run_id,
            success=False,
            error="用户取消任务；公司尚未开始处理",
            error_code=TaskCancelled.error_code,
        )
