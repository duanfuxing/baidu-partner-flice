from __future__ import annotations

import queue
import threading

import pytest

from src.errors import TaskCancelled
from src.gui import DesktopApplication


def test_login_wait_can_be_cancelled_without_tk_window() -> None:
    app = object.__new__(DesktopApplication)
    app.events = queue.Queue()
    app.cancel_event = threading.Event()
    app.cancel_event.set()

    with pytest.raises(TaskCancelled, match="取消登录"):
        app._wait_for_login_confirmation("请登录")

    event = app.events.get_nowait()
    assert event[0] == "login_required"
