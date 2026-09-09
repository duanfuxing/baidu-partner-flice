from __future__ import annotations

import queue
import threading
from pathlib import Path

import customtkinter as ctk
import pytest

from src.errors import TaskCancelled
from src.gui import (
    Palette,
    WINDOWS_MONOSPACE_FONT_FAMILY,
    WINDOWS_UI_FONT_FAMILY,
    DesktopApplication,
    configure_platform_fonts,
    platform_monospace_font_family,
)


class _WidgetStub:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.options: dict[str, object] = {}

    def get(self) -> str:
        return self.value

    def set(self, value: object) -> None:
        self.value = str(value)

    def configure(self, **kwargs: object) -> None:
        self.options.update(kwargs)

    def stop(self) -> None:
        self.options["stopped"] = True


def test_login_wait_can_be_cancelled_without_tk_window() -> None:
    app = object.__new__(DesktopApplication)
    app.events = queue.Queue()
    app.cancel_event = threading.Event()
    app.cancel_event.set()

    with pytest.raises(TaskCancelled, match="取消登录"):
        app._wait_for_login_confirmation("请登录")

    event = app.events.get_nowait()
    assert event[0] == "login_required"


def test_windows_uses_microsoft_system_fonts() -> None:
    original_family = ctk.ThemeManager.theme["CTkFont"]["family"]
    try:
        configure_platform_fonts("Windows")
        assert ctk.ThemeManager.theme["CTkFont"]["family"] == WINDOWS_UI_FONT_FAMILY
        assert (
            platform_monospace_font_family("Windows")
            == WINDOWS_MONOSPACE_FONT_FAMILY
        )
    finally:
        ctk.ThemeManager.theme["CTkFont"]["family"] = original_family


def test_finish_running_keeps_cached_input_path(tmp_path: Path) -> None:
    app = object.__new__(DesktopApplication)
    app.running = True
    app.login_event = threading.Event()
    app.report = object()
    app.input_path = _WidgetStub(str(tmp_path))
    app.validation_title = _WidgetStub()
    app.validation_meta = _WidgetStub()
    app.login_button = _WidgetStub()
    app.cancel_button = _WidgetStub()
    app.run_progress = _WidgetStub()
    app._reset_stats = lambda: None
    app._show_validation_view = lambda view: None
    app._set_controls_busy = lambda busy: None

    app._finish_running()

    assert app.input_path.get() == str(tmp_path)
    assert app.report is None
    assert app.validation_meta.options["text"] == "当前目录需重新验证"


def test_application_palette_is_gray_white_and_light_blue() -> None:
    assert Palette.APP_BG == "#F4F7FB"
    assert Palette.SURFACE == "#FFFFFF"
    assert Palette.SIDEBAR == "#FFFFFF"
    assert Palette.PRIMARY_SOFT == "#EAF4FF"


def test_run_job_passes_browser_selection_to_scheduler(monkeypatch, tmp_path):
    from unittest.mock import Mock
    import src.gui as module
    app = object.__new__(DesktopApplication)
    app.data_directories = {'auth': tmp_path, 'screenshots': tmp_path}
    app.events = queue.Queue()
    app.cancel_event = threading.Event()
    monkeypatch.setattr(module, 'create_run_log', lambda: tmp_path/'run.log')
    monkeypatch.setattr(module, 'configure_logging', lambda _: None)
    monkeypatch.setattr(module, 'validate_input_directory', lambda _: object())
    run = Mock(return_value={'successes': [], 'failures': []})
    monkeypatch.setattr(module, 'run_validated_companies', run)
    executable = tmp_path/'edge.exe'
    app._run_job(tmp_path, False, 'msedge', executable)
    config = run.call_args.kwargs['browser_config']
    assert config.chrome_channel == 'msedge'
    assert config.executable_path == executable
