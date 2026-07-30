from __future__ import annotations

import struct
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS = PROJECT_ROOT / "assets"


def test_source_png_is_large_rgba_image() -> None:
    payload = (ASSETS / "app-icon-v3.png").read_bytes()

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
    assert "icon=windows_icon" in spec
    assert "icon=macos_icon" in spec
