"""冻结桌面应用入口。"""

from __future__ import annotations


if __name__ == "__main__":
    # PyInstaller 冻结程序必须在导入 GUI 和业务模块前分流 worker 参数。
    import multiprocessing
    import sys

    multiprocessing.freeze_support()

    if "--self-check" in sys.argv:
        from src.self_check import run_self_check

        raise SystemExit(0 if run_self_check() else 1)
    else:
        from src.gui import main

        raise SystemExit(main())
