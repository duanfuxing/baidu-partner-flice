"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .application import (
    is_run_successful,
    run_validated_companies,
    validate_input_directory,
)
from .browser import BrowserConfig
from .errors import FliceError, InputPersistenceError, InputValidationError
from .run_logging import configure_logging, create_run_log
from .workflow import WorkflowConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="百度客户资质流程 1-6 自动化")
    parser.add_argument("--input", type=Path, default=Path("input"), help="输入目录，默认 input")
    parser.add_argument(
        "--auth-state",
        type=Path,
        default=Path(".auth/storage_state.json"),
        help="Playwright 登录状态文件",
    )
    parser.add_argument("--screenshots", action="store_true", help="流程失败时保存页面截图")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫描并验证流程 6 执行计划，不删除、添加、上传或提交",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="兼容参数；worker 完成或失败后都会自动关闭 Chrome",
    )
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_file = create_run_log()
    configure_logging(log_file, level=args.log_level, console=True)
    logging.info("任务日志：%s", log_file)
    try:
        report = validate_input_directory(args.input)
    except (InputValidationError, InputPersistenceError) as exc:
        logging.error("%s", exc)
        return 2

    browser_config = BrowserConfig(
        auth_state_path=args.auth_state.expanduser().resolve(),
        screenshot_dir=Path("screenshots").resolve(),
    )
    workflow_config = WorkflowConfig(
        capture_screenshots=args.screenshots,
        dry_run=args.dry_run,
    )
    try:
        result = run_validated_companies(
            report,
            browser_config=browser_config,
            workflow_config=workflow_config,
            login_prompt=input,
            log_level=args.log_level,
            log_file=log_file,
        )
    except FliceError as exc:
        logging.error("%s", exc)
        return 1
    except Exception as exc:
        logging.error("运行失败：%s", exc)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if is_run_successful(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
