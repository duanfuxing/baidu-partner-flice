"""Playwright Chrome 会话和人工登录处理。"""

from __future__ import annotations

import re
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .errors import AuthenticationRequired, PageFlowError

WORKBENCH_URL = "https://partner.baidu.com/portal/workbench"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowserConfig:
    auth_state_path: Path = Path(".auth/storage_state.json")
    chrome_channel: str = "chrome"
    headless: bool = False
    timeout_ms: int = 30_000
    screenshot_dir: Path = Path("screenshots")


def is_truth_submit_url(url: str) -> bool:
    """判断是否进入了带动态参数的真实性资质提交页面。"""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == "fkzhunru.baidu.com"
        and parsed.path.rstrip("/") == "/flice"
        and parsed.fragment.startswith("/truth/submit")
    )


class BrowserSession:
    """管理 Playwright、Chrome 和登录状态。"""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or BrowserConfig()
        self._playwright = None
        self.browser = None
        self.context = None

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self.browser = self._playwright.chromium.launch(
                channel=self.config.chrome_channel,
                headless=self.config.headless,
            )
            context_kwargs = {
                "viewport": {"width": 1440, "height": 1000},
                "locale": "zh-CN",
            }
            if self.config.auth_state_path.is_file():
                context_kwargs["storage_state"] = str(self.config.auth_state_path)
            try:
                self.context = self.browser.new_context(**context_kwargs)
            except PlaywrightError:
                # 登录状态文件损坏或版本不兼容时，使用空上下文进入人工登录流程；
                # 不删除原文件，便于用户排查和恢复。
                context_kwargs.pop("storage_state", None)
                self.context = self.browser.new_context(**context_kwargs)
            self.context.set_default_timeout(self.config.timeout_ms)
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self.context is not None:
            self.context.close()
            self.context = None
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def new_page(self):
        if self.context is None:
            raise PageFlowError("浏览器上下文尚未启动")
        return self.context.new_page()

    @staticmethod
    def _is_login_page(page) -> bool:
        url = page.url.casefold()
        return "passport.baidu.com" in url or "/login" in url or "login" in url

    def _looks_logged_in(self, page) -> bool:
        """判断页面是否已经脱离登录页。

        登录后页面可能停留在工作台、跳到客户管理页，或者在新标签页完成跳转，
        因此不能只要求固定的完整 URL 和某一个页面文字。
        """

        url = page.url.casefold()
        if self._is_login_page(page) or "partner.baidu.com" not in url:
            return False
        try:
            body_text = page.locator("body").inner_text(timeout=1_000)
        except Exception:
            return False
        logged_in_markers = ("工作台", "客户资质", "百度推广", "管理中心", "客户管理")
        login_markers = ("扫码登录", "账号登录", "登录百度账号")
        has_logged_in_marker = any(keyword in body_text for keyword in logged_in_markers)
        has_login_marker = any(keyword in body_text for keyword in login_markers)
        return (has_logged_in_marker or "/portal/workbench" in url) and not has_login_marker

    def _find_logged_in_page(self, preferred_page=None):
        pages = list(reversed(self.context.pages if self.context is not None else []))
        if preferred_page is not None and preferred_page in pages:
            pages.remove(preferred_page)
            pages.insert(0, preferred_page)
        for candidate in pages:
            try:
                if self._looks_logged_in(candidate):
                    return candidate
            except Exception:
                continue
        return None

    def _wait_for_logged_in_page(self, preferred_page=None, timeout_ms: int = 10_000):
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            logged_in_page = self._find_logged_in_page(preferred_page)
            if logged_in_page is not None:
                return logged_in_page
            if time.monotonic() >= deadline:
                return None
            try:
                preferred_page.wait_for_timeout(250)
            except Exception:
                return None

    def ensure_logged_in(self, prompt: Callable[[str], str] = input):
        """打开工作台；没有登录时等待人工登录并保存状态。"""

        page = self.new_page()
        page.goto(WORKBENCH_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        logged_in_page = self._find_logged_in_page(page)
        if logged_in_page is None:
            LOGGER.info("未检测到登录状态，需要人工登录")
            prompt("Chrome 已打开，请人工完成百度登录；完成后在软件中确认继续。")
            LOGGER.info("已收到人工确认，正在验证登录状态")
            logged_in_page = self._wait_for_logged_in_page(page)
            if logged_in_page is None:
                raise AuthenticationRequired(
                    "人工确认后仍未检测到登录成功，请确认已进入百度代理商工作台后重试"
                )
        else:
            LOGGER.info("已检测到登录状态，跳过人工登录")
        page = logged_in_page
        self._save_storage_state()
        return page

    def _save_storage_state(self) -> None:
        if self.context is None:
            raise PageFlowError("浏览器上下文尚未启动")
        self.config.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=str(self.config.auth_state_path))

    def save_failure_screenshot(self, page, company_name: str, step: str) -> Path | None:
        """保存脱敏范围由调用方控制的页面截图；默认仅在显式调用时执行。"""

        try:
            safe_name = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", company_name).strip("_") or "company"
            safe_step = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", step).strip("_") or "step"
            self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = self.config.screenshot_dir / f"{safe_name}-{safe_step}.png"
            page.screenshot(path=str(path), full_page=True)
            return path
        except Exception:
            return None
