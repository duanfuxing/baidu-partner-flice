"""Playwright Chrome 会话和人工登录处理。"""

from __future__ import annotations

import re
import logging
import os
import plistlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .errors import AuthenticationRequired, PageFlowError

WORKBENCH_URL = "https://partner.baidu.com/portal/workbench"
LOGGER = logging.getLogger(__name__)

BROWSER_CHANNELS = {"Google Chrome": "chrome", "Microsoft Edge": "msedge", "其他 Chromium 浏览器": ""}


def resolve_browser_path(value: str) -> Path | None:
    if not value.strip():
        return None
    path = Path(value.strip()).expanduser().resolve()
    if path.is_dir() and path.suffix.lower() == ".app":
        try:
            with (path / "Contents/Info.plist").open("rb") as stream:
                executable = plistlib.load(stream)["CFBundleExecutable"]
            if not isinstance(executable, str) or Path(executable).name != executable:
                raise ValueError("无效的应用程序入口")
            path = path / "Contents/MacOS" / executable
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("无法读取浏览器 .app，请选择有效的浏览器应用") from exc
    if not path.is_file():
        raise ValueError("浏览器程序不存在，请重新选择程序路径")
    if sys.platform == "win32" and path.suffix.lower() != ".exe":
        raise ValueError("请选择浏览器的 .exe 程序")
    if sys.platform != "win32" and not os.access(path, os.X_OK):
        raise ValueError("所选文件不可执行，请选择浏览器程序")
    return path


def _find_windows_chrome() -> Path | None:
    if sys.platform != "win32":
        return None
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidate = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if candidate.is_file():
                return candidate
    return None


@dataclass(frozen=True)
class BrowserConfig:
    auth_state_path: Path = Path(".auth/storage_state.json")
    chrome_channel: str = "chrome"
    headless: bool = False
    timeout_ms: int = 30_000
    screenshot_dir: Path = Path("screenshots")
    executable_path: Path | None = None


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


def is_new_audit_landing_url(url: str) -> bool:
    """判断是否为新版资质统一管理中心首页。"""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == "fkzhunru.baidu.com"
        and parsed.path.rstrip("/") == "/newaudit"
        and parsed.fragment.startswith("/lice/")
        and not parsed.fragment.startswith("/lice/submit/")
    )


def is_qualification_submit_url(url: str) -> bool:
    """判断是否进入旧版或新版资质提交概览页面。"""

    if is_truth_submit_url(url):
        return True
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == "fkzhunru.baidu.com"
        and parsed.path.rstrip("/") == "/newaudit"
        and parsed.fragment.startswith("/lice/submit/")
    )


def is_new_audit_qualification_detail_url(url: str) -> bool:
    """判断是否为新版 URL 投放资质详情页面。"""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == "fkzhunru.baidu.com"
        and parsed.path.rstrip("/") == "/newaudit"
        and parsed.fragment.startswith("/lice/invest_lice_list/")
    )


def is_new_audit_add_qualification_url(url: str) -> bool:
    """判断是否为新版新增投放资质页面。"""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == "fkzhunru.baidu.com"
        and parsed.path.rstrip("/") == "/newaudit"
        and parsed.fragment.startswith("/lice/add_invest_lice/")
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
            launch_options = {"headless": self.config.headless, "timeout": self.config.timeout_ms}
            if self.config.executable_path is not None:
                launch_options["executable_path"] = str(resolve_browser_path(str(self.config.executable_path)))
            else:
                if not self.config.chrome_channel:
                    raise PageFlowError("请为其他 Chromium 浏览器选择程序路径")
                launch_options["channel"] = self.config.chrome_channel
            try:
                self.browser = self._playwright.chromium.launch(**launch_options)
            except PlaywrightError as exc:
                channel = self.config.chrome_channel
                if self.config.executable_path is not None or channel not in {"chrome", "msedge"} or (
                    f"Chromium distribution '{channel}' is not found" not in str(exc)
                ):
                    raise
                executable = _find_windows_chrome() if channel == "chrome" else None
                if executable is None:
                    name = "Google Chrome" if channel == "chrome" else "Microsoft Edge"
                    raise PageFlowError(
                        f"未找到 {name} 浏览器。请先安装 {name} 正式版，"
                        "或在设置页面选择已安装浏览器的程序路径。"
                    ) from exc
                self.browser = self._playwright.chromium.launch(
                    executable_path=str(executable),
                    headless=self.config.headless,
                    timeout=self.config.timeout_ms,
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
            self._pause_before_error_close()
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is not None:
            self._pause_before_error_close()
        self.close()

    def _pause_before_error_close(self) -> None:
        """有可见页面的错误退出保留5秒，供人工观察，不改变原始异常。"""
        try:
            if (self.config.headless or self.browser is None
                    or not self.browser.is_connected() or self.context is None
                    or not any(not page.is_closed() for page in self.context.pages)):
                return
            LOGGER.error('发生错误，保留当前页面5秒后关闭浏览器，请查看页面提示')
            time.sleep(5)
        except Exception:
            # 页面已关闭或连接失效时继续原有资源清理。
            pass

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

    def _wait_for_logged_in_page(self, preferred_page=None, timeout_ms: int | None = None):
        timeout_ms = self.config.timeout_ms if timeout_ms is None else timeout_ms
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
            page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
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
