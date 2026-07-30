"""项目根目录入口。"""

import multiprocessing

from src.cli import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
