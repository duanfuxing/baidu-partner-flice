"""桌面应用和命令行共用的任务日志管理。"""

from __future__ import annotations

import codecs
import logging
import os
import platform
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

APP_DIRECTORY_NAME = "BaiduPartnerFlice"
LOG_FORMAT = "%(asctime)s %(levelname)s %(processName)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def application_data_dir() -> Path:
    """返回当前用户可写的应用数据目录。"""

    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif system == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_STATE_HOME")
        root = Path(base) if base else Path.home() / ".local" / "state"
    return root / APP_DIRECTORY_NAME


def create_run_log(log_directory: Path | None = None) -> Path:
    directory = log_directory or application_data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return directory / f"run-{timestamp}-{uuid.uuid4().hex[:8]}.log"


class CallbackLogHandler(logging.Handler):
    """将格式化日志送入桌面线程事件队列。"""

    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.callback(self.format(record))
        except Exception:
            self.handleError(record)


def _mark_handler(handler: logging.Handler) -> logging.Handler:
    setattr(handler, "_baidu_flice_handler", True)
    return handler


def configure_logging(
    log_file: Path,
    *,
    level: str = "INFO",
    live_callback: Callable[[str], None] | None = None,
    console: bool = False,
    message_prefix: str = "",
) -> None:
    """配置本次任务日志，不移除测试框架或宿主添加的其他处理器。"""

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_baidu_flice_handler", False):
            root.removeHandler(handler)
            handler.close()

    numeric_level = getattr(logging, level)
    root.setLevel(numeric_level)
    formatter = logging.Formatter(
        LOG_FORMAT.replace("%(message)s", f"{message_prefix}%(message)s"),
        datefmt=LOG_DATE_FORMAT,
    )

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = _mark_handler(logging.FileHandler(log_file, encoding="utf-8"))
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console and sys.stderr is not None:
        console_handler = _mark_handler(logging.StreamHandler())
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if live_callback is not None:
        callback_handler = _mark_handler(CallbackLogHandler(live_callback))
        callback_handler.setLevel(numeric_level)
        callback_handler.setFormatter(formatter)
        root.addHandler(callback_handler)


def list_run_logs(log_directory: Path | None = None) -> tuple[Path, ...]:
    directory = log_directory or application_data_dir() / "logs"
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in directory.glob("run-*.log") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    )


class IncrementalLogReader:
    """按新增字节读取 UTF-8 日志，并处理跨读取字符及文件替换。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.identity: tuple[int, int] | None = None
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def read_new(self) -> tuple[str, bool]:
        """返回新增文本和是否因截断/替换而重置。"""

        try:
            stat = self.path.stat()
        except OSError:
            return "", False
        identity = (stat.st_dev, stat.st_ino)
        reset = (
            self.identity is not None
            and (identity != self.identity or stat.st_size < self.offset)
        )
        if reset:
            self.offset = 0
            self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.identity = identity
        try:
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read()
                self.offset = stream.tell()
        except OSError:
            return "", reset
        return self.decoder.decode(data, final=False) if data else "", reset
