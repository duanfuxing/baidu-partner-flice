from unittest.mock import Mock

import pytest

from src.browser import BrowserSession, is_truth_submit_url
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
