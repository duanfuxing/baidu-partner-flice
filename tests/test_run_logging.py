from __future__ import annotations

import logging
from pathlib import Path

from src.run_logging import (
    IncrementalLogReader,
    configure_logging,
    create_run_log,
    list_run_logs,
)


def test_create_and_list_run_logs_newest_first(tmp_path: Path) -> None:
    first = create_run_log(tmp_path)
    first.write_text("first", encoding="utf-8")
    second = create_run_log(tmp_path)
    second.write_text("second", encoding="utf-8")
    first.touch()
    second.touch()

    logs = list_run_logs(tmp_path)

    assert set(logs) == {first, second}
    assert all(path.name.startswith("run-") for path in logs)


def test_configure_logging_writes_utf8_task_log(tmp_path: Path) -> None:
    log_file = tmp_path / "run-test.log"
    configure_logging(log_file)

    logging.getLogger("test").info("中文运行日志")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "中文运行日志" in log_file.read_text(encoding="utf-8")


def test_incremental_log_reader_only_returns_new_utf8_text(tmp_path: Path) -> None:
    path = tmp_path / "run.log"
    encoded = "中文".encode("utf-8")
    path.write_bytes(encoded[:2])
    reader = IncrementalLogReader(path)

    assert reader.read_new() == ("", False)
    with path.open("ab") as stream:
        stream.write(encoded[2:])

    assert reader.read_new() == ("中文", False)
    assert reader.read_new() == ("", False)


def test_incremental_log_reader_resets_after_truncation(tmp_path: Path) -> None:
    path = tmp_path / "run.log"
    path.write_text("old content", encoding="utf-8")
    reader = IncrementalLogReader(path)
    assert reader.read_new() == ("old content", False)

    path.write_text("new", encoding="utf-8")

    assert reader.read_new() == ("new", True)
