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
    app._run_job(tmp_path, False, 'msedge', executable, 120_000)
    config = run.call_args.kwargs['browser_config']
    assert config.chrome_channel == 'msedge'
    assert config.executable_path == executable
    assert config.timeout_ms == 120_000
    assert run.call_args.kwargs['workflow_config'].page_timeout_ms == 120_000


def test_invalid_timeout_prevents_start(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import src.gui as module
    app = object.__new__(DesktopApplication)
    app.running = False
    app.report = SimpleNamespace(input_root=tmp_path)
    app.input_path = _WidgetStub(str(tmp_path))
    app.final_submit = _WidgetStub('')
    app.timeout_seconds = _WidgetStub('0')
    app._show_page = Mock()
    error = Mock()
    monkeypatch.setattr(module.messagebox, 'showerror', error)
    app._start_run()
    error.assert_called_once()
    assert error.call_args.args[0] == '超时设置无效'
    assert app.running is False


@pytest.mark.parametrize('confirmed', [False, True])
def test_history_delete_requires_confirmation(monkeypatch, tmp_path, confirmed):
    from unittest.mock import Mock
    import src.gui as module
    app=object.__new__(DesktopApplication)
    path=tmp_path/'run-example.log';path.write_text('log',encoding='utf-8')
    app.selected_history_path=path;app.running=False;app.current_log=None
    app.data_directories={'logs':tmp_path};app._refresh_log_history=Mock()
    monkeypatch.setattr(module.messagebox,'askyesno',lambda *args:confirmed)
    app._delete_history_log()
    assert path.exists() is not confirmed
    assert app._refresh_log_history.call_count == int(confirmed)


def test_history_delete_blocks_running_log(monkeypatch, tmp_path):
    from unittest.mock import Mock
    import src.gui as module
    app=object.__new__(DesktopApplication)
    path=tmp_path/'run-example.log';path.write_text('log',encoding='utf-8')
    app.selected_history_path=path;app.running=True;app.current_log=path
    warning=Mock();monkeypatch.setattr(module.messagebox,'showwarning',warning)
    app._delete_history_log()
    warning.assert_called_once();assert path.exists()


def test_history_delete_failure_keeps_selection(monkeypatch, tmp_path):
    from unittest.mock import Mock
    import src.gui as module
    app=object.__new__(DesktopApplication)
    path=tmp_path/'run-example.log';path.write_text('log',encoding='utf-8')
    app.selected_history_path=path;app.running=False;app.current_log=None
    app.data_directories={'logs':tmp_path};app._refresh_log_history=Mock()
    monkeypatch.setattr(module.messagebox,'askyesno',lambda *args:True)
    monkeypatch.setattr(module,'delete_run_log',Mock(side_effect=PermissionError('file in use')))
    error=Mock();monkeypatch.setattr(module.messagebox,'showerror',error)
    app._delete_history_log()
    error.assert_called_once();assert path.exists()
    assert app.selected_history_path==path
    app._refresh_log_history.assert_not_called()
