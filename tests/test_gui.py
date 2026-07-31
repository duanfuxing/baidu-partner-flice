from __future__ import annotations

import queue
import threading

import customtkinter as ctk
import pytest

from src.errors import TaskCancelled
from src.gui import (
    WINDOWS_MONOSPACE_FONT_FAMILY,
    WINDOWS_UI_FONT_FAMILY,
    DesktopApplication,
    configure_platform_fonts,
    platform_monospace_font_family,
)


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
