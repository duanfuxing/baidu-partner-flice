from __future__ import annotations

import sys
from pathlib import Path

from src.resources import application_asset_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_application_asset_path_uses_project_root_in_development(
    monkeypatch,
) -> None:
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert application_asset_path("app-icon.png") == (
        PROJECT_ROOT / "assets" / "app-icon.png"
    )


def test_application_asset_path_uses_pyinstaller_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert application_asset_path("app-icon.png") == (
        tmp_path / "assets" / "app-icon.png"
    )


def test_sidebar_uses_formal_icon_without_serial_submission_copy() -> None:
    gui_source = (PROJECT_ROOT / "src" / "gui.py").read_text(encoding="utf-8")

    assert 'application_asset_path("app-icon.png")' in gui_source
    assert "self.brand_icon = ctk.CTkImage(" in gui_source
    assert "self.root.iconphoto(True, self.window_icon)" in gui_source
    assert "单 worker · 串行提交" not in gui_source
