from __future__ import annotations

import struct
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS = PROJECT_ROOT / "assets"
EXPECTED_VERSION = "0.30.5"


def test_source_png_is_large_rgba_image() -> None:
    payload = (ASSETS / "app-icon.png").read_bytes()

    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, bit_depth, color_type, _, _, _ = struct.unpack(
        ">IIBBBBB",
        payload[16:29],
    )
    assert width >= 1024
    assert height >= 1024
    assert bit_depth == 8
    assert color_type == 6


def test_windows_icon_contains_common_sizes() -> None:
    payload = (ASSETS / "app-icon.ico").read_bytes()
    reserved, icon_type, count = struct.unpack("<HHH", payload[:6])
    sizes = {
        256 if payload[6 + index * 16] == 0 else payload[6 + index * 16]
        for index in range(count)
    }

    assert reserved == 0
    assert icon_type == 1
    assert count >= 7
    assert {16, 24, 32, 48, 64, 128, 256}.issubset(sizes)


def test_macos_icon_has_valid_icns_header() -> None:
    payload = (ASSETS / "app-icon.icns").read_bytes()

    assert payload[:4] == b"icns"
    assert struct.unpack(">I", payload[4:8])[0] == len(payload)
    assert len(payload) > 100_000


def test_pyinstaller_spec_uses_platform_icons() -> None:
    spec = (PROJECT_ROOT / "packaging" / "BaiduPartnerFlice.spec").read_text(
        encoding="utf-8"
    )

    assert '"assets" / "app-icon.ico"' in spec
    assert '"assets" / "app-icon.icns"' in spec
    assert '"assets" / "app-icon.png"' in spec
    assert 'app_assets = [(' in spec
    assert 'datas=playwright_datas + ctk_datas + app_assets' in spec
    assert 'name="百度资质自动提交工具.app"' in spec
    assert "icon=windows_icon" in spec
    assert "icon=macos_icon" in spec


def test_desktop_package_versions_are_consistent() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_init = (PROJECT_ROOT / "src" / "__init__.py").read_text(
        encoding="utf-8"
    )
    windows_version = (
        PROJECT_ROOT / "packaging" / "version_info.txt"
    ).read_text(encoding="utf-8")
    spec = (
        PROJECT_ROOT / "packaging" / "BaiduPartnerFlice.spec"
    ).read_text(encoding="utf-8")
    workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "build-desktop.yml"
    ).read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == EXPECTED_VERSION
    assert f'__version__ = "{EXPECTED_VERSION}"' in package_init
    assert "filevers=(0, 30, 5, 0)" in windows_version
    assert "prodvers=(0, 30, 5, 0)" in windows_version
    assert windows_version.count(f'"{EXPECTED_VERSION}"') == 2
    assert spec.count(f'"{EXPECTED_VERSION}"') == 3
    assert workflow.count(f"artifact: BaiduPartnerFlice-{EXPECTED_VERSION}-") == 4
    assert "pattern: BaiduPartnerFlice-*" in workflow
    assert "artifact: 百度资质自动提交工具-" not in workflow
    assert '--title "百度资质自动提交工具 $GITHUB_REF_NAME"' in workflow
    assert "BaiduPartnerFlice.exe" in workflow
