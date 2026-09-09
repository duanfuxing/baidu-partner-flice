from __future__ import annotations

import logging
from pathlib import Path

from src.run_logging import (
    APPLICATION_DATA_SUBDIRECTORIES,
    IncrementalLogReader,
    configure_logging,
    create_run_log,
    ensure_application_data_directories,
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


def test_application_data_subdirectories_are_created(tmp_path: Path) -> None:
    directories = ensure_application_data_directories(tmp_path)

    assert set(directories) == set(APPLICATION_DATA_SUBDIRECTORIES)
    assert all(path.is_dir() for path in directories.values())
    assert directories["auth"] == tmp_path / "auth"
    assert directories["logs"] == tmp_path / "logs"
    assert directories["screenshots"] == tmp_path / "screenshots"
    assert directories["cache"] == tmp_path / "cache"


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


def test_delete_history_log_protects_active_and_outside_files(tmp_path):
    import pytest
    from src.run_logging import delete_run_log
    directory=tmp_path/'logs'; directory.mkdir()
    path=directory/'run-test.log'; path.write_text('test',encoding='utf-8')
    with pytest.raises(ValueError,match='正在使用'):
        delete_run_log(path,log_directory=directory,active_log=path)
    other=tmp_path/'run-other.log';other.write_text('keep',encoding='utf-8')
    with pytest.raises(ValueError,match='只能删除'):
        delete_run_log(other,log_directory=directory)
    link=directory/'run-link.log';link.symlink_to(other)
    with pytest.raises(ValueError,match='只能删除'):
        delete_run_log(link,log_directory=directory)
    delete_run_log(path,log_directory=directory)
    assert not path.exists()
    assert other.exists()


def test_delete_history_closes_own_file_handler(tmp_path):
    import logging
    from src.run_logging import delete_run_log
    path=tmp_path/'run-test.log'
    handler=logging.FileHandler(path,encoding='utf-8');handler._baidu_flice_handler=True
    logging.getLogger().addHandler(handler)
    try:
        delete_run_log(path,log_directory=tmp_path)
        assert handler.stream is None
        assert handler not in logging.getLogger().handlers
        assert not path.exists()
    finally:
        logging.getLogger().removeHandler(handler);handler.close()
