from unittest.mock import Mock

import pytest

from src.browser import BrowserConfig, BrowserSession


@pytest.mark.parametrize('mode', ['error', 'success', 'headless', 'no_browser',
                                 'disconnected', 'no_pages', 'closed_page', 'wait_error'])
def test_error_close_waits_only_for_open_visible_browser(monkeypatch, mode, caplog):
    session = BrowserSession(BrowserConfig(headless=mode == 'headless'))
    session.browser = Mock()
    session.browser.is_connected.return_value = mode != 'disconnected'
    page = Mock()
    page.is_closed.return_value = mode == 'closed_page'
    session.context = Mock()
    session.context.pages = [] if mode == 'no_pages' else [page]
    if mode == 'no_browser':
        session.browser = None
    actions = []

    def sleep(seconds):
        actions.append(('wait', seconds))
        if mode == 'wait_error':
            raise RuntimeError('wait interrupted')

    monkeypatch.setattr('src.browser.time.sleep', sleep)
    monkeypatch.setattr(BrowserSession, '__enter__', lambda self: self)
    monkeypatch.setattr(session, 'close', lambda: actions.append(('close',)))
    if mode == 'success':
        with session:
            pass
    else:
        original = ValueError('original error')
        with pytest.raises(ValueError) as error:
            with session:
                raise original
        assert error.value is original
    expected = [('wait', 5), ('close',)] if mode in ('error', 'wait_error') else [('close',)]
    assert actions == expected
    if mode == 'error':
        assert '5秒后关闭浏览器' in caplog.text
