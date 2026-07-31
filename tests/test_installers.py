from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "build-desktop.yml"
INSTALLER_PATH = PROJECT_ROOT / "packaging" / "windows-installer.iss"
X64_INSTALLER_PATH = PROJECT_ROOT / "packaging" / "windows-installer-x64.iss"
ARM64_INSTALLER_PATH = PROJECT_ROOT / "packaging" / "windows-installer-arm64.iss"
EXPECTED_VERSION = "0.30.5"


def test_workflow_builds_four_native_installers() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "os: windows-2022" in workflow
    assert "python_architecture: x64" in workflow
    assert "os: windows-11-arm" in workflow
    assert "python_architecture: arm64" in workflow
    assert (
        f"package: BaiduPartnerFlice-{EXPECTED_VERSION}-Windows-x64-Setup.exe"
        in workflow
    )
    assert (
        f"package: BaiduPartnerFlice-{EXPECTED_VERSION}-Windows-arm64-Setup.exe"
        in workflow
    )
    assert (
        f"package: BaiduPartnerFlice-{EXPECTED_VERSION}-macOS-arm64-Installer.pkg"
        in workflow
    )
    assert (
        f"package: BaiduPartnerFlice-{EXPECTED_VERSION}-macOS-x64-Installer.pkg"
        in workflow
    )
    assert "Compress-Archive" not in workflow
    assert "ditto -c -k" not in workflow


def test_windows_installer_places_onedir_bundle_in_program_files() -> None:
    installer = INSTALLER_PATH.read_text(encoding="utf-8")

    assert f'#define MyAppVersion "{EXPECTED_VERSION}"' in installer
    assert r"DefaultDirName={autopf}\BaiduPartnerFlice" in installer
    assert (
        r'Source: "..\dist\BaiduPartnerFlice\*"; DestDir: "{app}"; '
        "Flags: ignoreversion recursesubdirs createallsubdirs"
        in installer
    )
    assert r'Filename: "{app}\{#MyAppExeName}"' in installer
    assert "{autoprograms}" in installer
    assert "{autodesktop}" in installer
    assert "UninstallDisplayIcon=" in installer


def test_windows_installers_are_architecture_specific_and_preserve_user_data() -> None:
    installer = INSTALLER_PATH.read_text(encoding="utf-8")
    x64_installer = X64_INSTALLER_PATH.read_text(encoding="utf-8")
    arm64_installer = ARM64_INSTALLER_PATH.read_text(encoding="utf-8")
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert '#define MyArchitecturesAllowed "x64compatible"' in x64_installer
    assert '#define MyArchitecturesAllowed "arm64"' in arm64_installer
    assert '#include "windows-installer.iss"' in x64_installer
    assert '#include "windows-installer.iss"' in arm64_installer
    assert "ArchitecturesAllowed={#MyArchitecturesAllowed}" in installer
    assert "ArchitecturesInstallIn64BitMode={#MyArchitecturesAllowed}" in installer
    assert "installer_script: packaging\\windows-installer-x64.iss" in workflow
    assert "installer_script: packaging\\windows-installer-arm64.iss" in workflow
    assert '"${{ matrix.installer_script }}"' in workflow
    assert "MyAppIsArm64" not in workflow
    assert "[UninstallDelete]" not in installer
    assert "{localappdata}" not in installer.lower()


def test_macos_pkg_installs_application_bundle_into_applications() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pkgbuild \\" in workflow
    assert '--install-location "/Applications"' in workflow
    assert '"dist/百度资质自动提交工具.app"' in workflow
    assert '--identifier "com.baidu.partner.flice"' in workflow
    assert f'--version "{EXPECTED_VERSION}"' in workflow
