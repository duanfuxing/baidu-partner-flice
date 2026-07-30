"""冻结桌面包的离线运行时自检。"""

from __future__ import annotations

import multiprocessing
import queue


def _spawn_probe(result_queue) -> None:
    result_queue.put("spawn-ok")


def run_self_check(*, check_spawn: bool = True) -> bool:
    """验证桌面运行依赖；不启动 Chrome，也不访问网络。"""

    import tkinter  # noqa: F401

    import customtkinter  # noqa: F401
    import portalocker  # noqa: F401
    from playwright.sync_api import sync_playwright  # noqa: F401

    if not check_spawn:
        return True

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(target=_spawn_probe, args=(result_queue,))
    process.start()
    process.join(timeout=20)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        return False
    if process.exitcode != 0:
        return False
    try:
        return result_queue.get(timeout=2) == "spawn-ok"
    except queue.Empty:
        return False
