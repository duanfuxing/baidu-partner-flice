from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.gui_settings import (
    LAST_INPUT_DIRECTORY_KEY,
    SETTINGS_FILENAME,
    load_last_input_directory,
    save_last_input_directory,
)


def test_save_and_load_last_input_directory(tmp_path: Path) -> None:
    cache_directory = tmp_path / "cache"
    selected = tmp_path / "中文公司输入"
    selected.mkdir()

    saved = save_last_input_directory(cache_directory, selected)

    assert saved == selected.resolve()
    assert load_last_input_directory(cache_directory) == selected.resolve()
    payload = json.loads(
        (cache_directory / SETTINGS_FILENAME).read_text(encoding="utf-8")
    )
    assert payload == {LAST_INPUT_DIRECTORY_KEY: str(selected.resolve())}
    assert not (cache_directory / f".{SETTINGS_FILENAME}.tmp").exists()


def test_save_overwrites_previous_directory(tmp_path: Path) -> None:
    cache_directory = tmp_path / "cache"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    save_last_input_directory(cache_directory, first)
    save_last_input_directory(cache_directory, second)

    assert load_last_input_directory(cache_directory) == second.resolve()


@pytest.mark.parametrize(
    "content",
    (
        "not-json",
        "[]",
        "{}",
        '{"lastInputDirectory": null}',
        '{"lastInputDirectory": ""}',
    ),
)
def test_load_ignores_invalid_settings(tmp_path: Path, content: str) -> None:
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    (cache_directory / SETTINGS_FILENAME).write_text(content, encoding="utf-8")

    assert load_last_input_directory(cache_directory) is None


def test_load_ignores_missing_or_non_directory_path(tmp_path: Path) -> None:
    cache_directory = tmp_path / "cache"
    cache_directory.mkdir()
    regular_file = tmp_path / "input.txt"
    regular_file.write_text("input", encoding="utf-8")

    for invalid_path in (tmp_path / "missing", regular_file):
        (cache_directory / SETTINGS_FILENAME).write_text(
            json.dumps({LAST_INPUT_DIRECTORY_KEY: str(invalid_path)}),
            encoding="utf-8",
        )
        assert load_last_input_directory(cache_directory) is None


def test_save_rejects_invalid_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="输入目录不存在或不是目录"):
        save_last_input_directory(tmp_path / "cache", tmp_path / "missing")


def test_browser_preferences_preserve_input_directory(tmp_path):
    from src.gui_settings import load_browser_settings, save_browser_settings
    cache = tmp_path / 'cache'
    save_last_input_directory(cache, tmp_path)
    save_browser_settings(cache, 'Microsoft Edge', '/custom/edge')
    save_last_input_directory(cache, tmp_path)
    assert load_browser_settings(cache) == ('Microsoft Edge', '/custom/edge')
    assert load_last_input_directory(cache) == tmp_path
    save_browser_settings(cache, 'Google Chrome', '')
    assert load_browser_settings(cache) == ('Google Chrome', '')


@pytest.mark.parametrize('value', ['5', '30', '120', '600', ' 60 '])
def test_timeout_setting_roundtrip(tmp_path, value):
    from src.gui_settings import save_timeout_seconds, load_timeout_seconds, save_browser_settings, load_browser_settings
    save_browser_settings(tmp_path, 'Microsoft Edge', '')
    save_timeout_seconds(tmp_path, value)
    save_last_input_directory(tmp_path, tmp_path)
    assert load_timeout_seconds(tmp_path) == int(value)
    assert load_browser_settings(tmp_path) == ('Microsoft Edge', '')


@pytest.mark.parametrize('value', ['', '0', '-1', '4', '601', '1.5', 'abc', '²'])
def test_invalid_timeout_rejected(tmp_path, value):
    from src.gui_settings import save_timeout_seconds, load_timeout_seconds
    with pytest.raises(ValueError, match='5–600'):
        save_timeout_seconds(tmp_path, value)
    assert load_timeout_seconds(tmp_path) == 30


def test_corrupt_timeout_cache_falls_back(tmp_path):
    from src.gui_settings import load_timeout_seconds
    (tmp_path / SETTINGS_FILENAME).write_text('{"timeoutSeconds": null}', encoding='utf-8')
    assert load_timeout_seconds(tmp_path) == 30
