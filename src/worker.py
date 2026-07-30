"""独立 Playwright/Chrome 公司执行进程。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .browser import BrowserConfig, BrowserSession
from .models import CompanyInput, as_serializable
from .run_logging import configure_logging
from .scheduler import ExecutionScheduler
from .workflow import WorkflowConfig, WorkflowRunner


def run_company_worker(
    company: CompanyInput,
    *,
    input_root: str,
    run_id: str,
    browser_config: BrowserConfig,
    workflow_config: WorkflowConfig,
    log_level: str,
    log_file: str | None = None,
) -> dict:
    """子进程入口；直接复用主进程保存的登录状态，不重复登录检测。"""

    if log_file:
        configure_logging(
            Path(log_file),
            level=log_level,
            message_prefix=f"[{company.company_name}] ",
        )
    else:
        logging.basicConfig(
            level=getattr(logging, log_level),
            format=f"%(levelname)s [{company.company_name}] %(message)s",
            force=True,
        )
    scheduler = ExecutionScheduler(input_root)
    scheduler.mark_running(
        company,
        run_id=run_id,
        worker_pid=os.getpid(),
    )
    try:
        logging.info("正在启动独立 Chrome")
        with BrowserSession(browser_config) as session:
            # worker 不再重复执行登录检查，但仍需立即创建一个可见页面。
            # 否则在接口查询阶段浏览器上下文中没有任何页面，macOS 上 Chrome
            # 窗口会消失，看起来像 worker 启动后立即退出。
            workbench_page = session.new_page()
            logging.info("独立 Chrome 已启动，开始处理公司")
            runner = WorkflowRunner(session, workflow_config)
            result = runner.run_company(company, workbench_page=workbench_page)
        serialized = as_serializable(result)
        scheduler.mark_completed(
            company,
            run_id=run_id,
            success=True,
            result_path=result.submission_result_path,
        )
        logging.info("公司处理完成，Chrome 已关闭")
        return {
            "success": True,
            "companyName": company.company_name,
            "result": serialized,
        }
    except Exception as exc:
        error = str(exc)
        error_code = getattr(exc, "error_code", None)
        try:
            scheduler.mark_completed(
                company,
                run_id=run_id,
                success=False,
                error=error,
                error_code=error_code,
            )
        except Exception as scheduler_exc:
            error = f"{error}；调度状态保存失败：{scheduler_exc}"
        logging.error("公司处理失败，Chrome 已关闭：%s", error)
        return {
            "success": False,
            "companyName": company.company_name,
            "error": error,
            "errorCode": error_code,
        }
