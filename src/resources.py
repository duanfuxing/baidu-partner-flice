"""开发环境与 PyInstaller 冻结环境共用的应用资源路径。"""

from __future__ import annotations

import sys
from pathlib import Path


def application_asset_path(filename: str) -> Path:
    """返回 assets 中指定应用资源的绝对路径。"""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        project_root = Path(frozen_root)
    else:
        project_root = Path(__file__).resolve().parents[1]
    return project_root / "assets" / filename
