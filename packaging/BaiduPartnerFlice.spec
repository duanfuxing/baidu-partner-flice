# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH).parent
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")
windows_version_file = (
    str(project_root / "packaging" / "version_info.txt")
    if sys.platform == "win32"
    else None
)
windows_icon = (
    str(project_root / "assets" / "app-icon.ico")
    if sys.platform == "win32"
    else None
)
macos_icon = str(project_root / "assets" / "app-icon.icns")

a = Analysis(
    [str(project_root / "desktop_main.py")],
    pathex=[str(project_root)],
    binaries=playwright_binaries + ctk_binaries,
    datas=playwright_datas + ctk_datas,
    hiddenimports=playwright_hiddenimports + ctk_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BaiduPartnerFlice",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=windows_version_file,
    icon=windows_icon,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BaiduPartnerFlice",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="BaiduPartnerFlice.app",
        icon=macos_icon,
        bundle_identifier="com.baidu.partner.flice",
        version="0.30.1",
        info_plist={
            "CFBundleDisplayName": "百度资质自动提交工具",
            "CFBundleShortVersionString": "0.30.1",
            "CFBundleVersion": "0.30.1",
            "NSHighResolutionCapable": True,
        },
    )
