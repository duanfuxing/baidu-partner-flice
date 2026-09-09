from unittest.mock import Mock

import pytest

from src.browser import (
    BrowserSession,
    is_new_audit_add_qualification_url,
    is_new_audit_landing_url,
    is_new_audit_qualification_detail_url,
    is_qualification_submit_url,
    is_truth_submit_url,
)
from src.errors import AuthenticationRequired


def test_truth_submit_url_accepts_dynamic_suffix() -> None:
    assert is_truth_submit_url(
        "https://fkzhunru.baidu.com/flice#/truth/submit/58400710/2/token/0"
    )


def test_truth_submit_url_accepts_http_castk_query() -> None:
    assert is_truth_submit_url(
        "http://fkzhunru.baidu.com/flice?castk=abc#/truth/submit/58400710/2/token/0"
    )


def test_truth_submit_url_rejects_initial_process_url() -> None:
    assert not is_truth_submit_url("http://fkzhunru.baidu.com/flice#/lice/process/58400710")


def test_truth_submit_url_rejects_wrong_host() -> None:
    assert not is_truth_submit_url("https://partner.baidu.com/flice#/truth/submit/1")


def test_new_audit_landing_url_accepts_dynamic_lice_route() -> None:
    assert is_new_audit_landing_url(
        "https://fkzhunru.baidu.com/newaudit#/lice/10001/1/20002/token"
    )


def test_qualification_submit_url_accepts_new_popup_route() -> None:
    assert is_qualification_submit_url(
        "https://fkzhunru.baidu.com/newaudit#/lice/submit/10001/1/20002/token/0"
    )


def test_qualification_submit_url_rejects_new_landing_route() -> None:
    assert not is_qualification_submit_url(
        "https://fkzhunru.baidu.com/newaudit#/lice/10001/1/20002/token"
    )


def test_new_audit_qualification_detail_url_accepts_dynamic_route() -> None:
    assert is_new_audit_qualification_detail_url(
        "https://fkzhunru.baidu.com/newaudit#/lice/invest_lice_list/10001/1/token/0/30003"
    )


def test_new_audit_qualification_detail_url_rejects_submit_route() -> None:
    assert not is_new_audit_qualification_detail_url(
        "https://fkzhunru.baidu.com/newaudit#/lice/submit/10001/1/token/0"
    )


def test_new_audit_add_qualification_url_accepts_dynamic_route() -> None:
    assert is_new_audit_add_qualification_url(
        "https://fkzhunru.baidu.com/newaudit#/lice/add_invest_lice/10001/1/token"
    )


def test_manual_login_confirmation_must_pass_page_verification() -> None:
    session = BrowserSession()
    page = Mock()
    session.new_page = Mock(return_value=page)
    session._find_logged_in_page = Mock(return_value=None)
    session._wait_for_logged_in_page = Mock(return_value=None)
    session._save_storage_state = Mock()
    prompts: list[str] = []

    with pytest.raises(AuthenticationRequired, match="仍未检测到登录成功"):
        session.ensure_logged_in(prompt=lambda message: prompts.append(message) or "")

    session._save_storage_state.assert_not_called()
    assert prompts and "按回车" not in prompts[0]


def test_manual_login_saves_state_only_after_verified_business_page() -> None:
    session = BrowserSession()
    page = Mock()
    logged_in_page = Mock()
    session.new_page = Mock(return_value=page)
    session._find_logged_in_page = Mock(return_value=None)
    session._wait_for_logged_in_page = Mock(return_value=logged_in_page)
    session._save_storage_state = Mock()

    result = session.ensure_logged_in(prompt=lambda _message: "")

    assert result is logged_in_page
    session._save_storage_state.assert_called_once_with()


@pytest.mark.parametrize("variable", ["ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"])
def test_find_windows_chrome(monkeypatch, tmp_path, variable) -> None:
    import src.browser as module

    for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv(variable, str(tmp_path))
    executable = tmp_path / "Google/Chrome/Application/chrome.exe"
    assert module._find_windows_chrome() is None
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake")
    assert module._find_windows_chrome() == executable


@pytest.mark.parametrize("scenario", ["normal", "fallback", "missing", "other"])
def test_browser_launch_chrome_errors(monkeypatch, tmp_path, scenario) -> None:
    import playwright.sync_api as api
    import src.browser as module
    from src.errors import PageFlowError

    driver = Mock()
    browser = Mock()
    error = api.Error(
        "Chromium distribution 'chrome' is not found at missing/chrome.exe"
        if scenario != "other" else "Browser crashed"
    )
    driver.chromium.launch.side_effect = [browser] if scenario == "normal" else [error, browser]
    manager = Mock()
    manager.start.return_value = driver
    monkeypatch.setattr(api, "sync_playwright", lambda: manager)
    executable = tmp_path / "chrome.exe"
    finder = Mock(return_value=executable if scenario == "fallback" else None)
    monkeypatch.setattr(module, "_find_windows_chrome", finder)
    session = BrowserSession(module.BrowserConfig(auth_state_path=tmp_path / "state.json"))

    if scenario in ("normal", "fallback"):
        with session:
            assert session.browser is browser
        if scenario == "fallback":
            driver.chromium.launch.assert_called_with(executable_path=str(executable), headless=False, timeout=30_000)
        else:
            finder.assert_not_called()
    else:
        with pytest.raises(PageFlowError if scenario == "missing" else api.Error) as caught:
            session.__enter__()
        if scenario == "missing":
            assert "请先安装 Google Chrome 正式版" in str(caught.value)
        else:
            assert caught.value is error
            finder.assert_not_called()
        assert driver.chromium.launch.call_count == 1
    driver.stop.assert_called_once()


def test_explicit_browser_path_has_priority(monkeypatch, tmp_path):
    import playwright.sync_api as api
    from src.browser import BrowserConfig
    executable = tmp_path / 'edge.exe'
    executable.write_bytes(b'fake')
    executable.chmod(0o755)
    manager = Mock()
    driver = manager.start.return_value
    monkeypatch.setattr(api, 'sync_playwright', lambda: manager)
    with BrowserSession(BrowserConfig(executable_path=executable, chrome_channel='msedge', auth_state_path=tmp_path/'state')):
        driver.chromium.launch.assert_called_once_with(executable_path=str(executable.resolve()), headless=False, timeout=30_000)


def test_resolve_macos_app_and_missing_path(tmp_path):
    import plistlib
    from src.browser import resolve_browser_path
    app = tmp_path / '浏览器.app'
    executable = app / 'Contents/MacOS/Browser.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fake')
    executable.chmod(0o755)
    with (app / 'Contents/Info.plist').open('wb') as stream:
        plistlib.dump({'CFBundleExecutable': 'Browser.exe'}, stream)
    assert resolve_browser_path(str(app)) == executable
    executable.unlink()
    with pytest.raises(ValueError, match='不存在'):
        resolve_browser_path(str(app))


def test_edge_missing_has_actionable_message(monkeypatch, tmp_path):
    import playwright.sync_api as api
    from src.browser import BrowserConfig
    from src.errors import PageFlowError
    manager = Mock()
    manager.start.return_value.chromium.launch.side_effect = api.Error("Chromium distribution 'msedge' is not found")
    monkeypatch.setattr(api, 'sync_playwright', lambda: manager)
    with pytest.raises(PageFlowError, match='Microsoft Edge'):
        with BrowserSession(BrowserConfig(chrome_channel='msedge')):
            pass
