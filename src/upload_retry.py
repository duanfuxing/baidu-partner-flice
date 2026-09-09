"""只在当前卡片明确未增加文件且请求结束时重试上传。"""

import logging
import time
from urllib.parse import urlsplit

from .errors import PageFlowError

LOGGER = logging.getLogger(__name__)
MAX_UPLOAD_RETRIES = 3


def is_upload_request(request):
    parsed = urlsplit(request.url)
    return (parsed.scheme == "https" and parsed.hostname == "fkzhunru.baidu.com"
            and parsed.path == "/permit/web/permit/savelicepic"
            and request.method.upper() == "POST")


def upload_with_retry(page, trigger, uploaded_count, validate, *, description, timeout_ms,
                      file_count=1):
    """返回本次成功响应；预览已存在而无成功响应时返回空列表，不重复传。"""
    baseline = uploaded_count()
    for attempt in range(MAX_UPLOAD_RETRIES + 1):
        requests, pending, responses = set(), set(), []

        def on_request(request):
            if is_upload_request(request):
                requests.add(request)
                pending.add(request)

        def on_response(response):
            if response.request in requests:
                responses.append(response)
                LOGGER.info("%s：上传接口返回 HTTP %s", description, response.status)

        def on_finished(request):
            pending.discard(request)

        handlers = {"request": on_request, "response": on_response,
                    "requestfinished": on_finished, "requestfailed": on_finished}
        for event, handler in handlers.items():
            page.on(event, handler)
        LOGGER.info("%s：%s，等待上传响应（%s 秒）", description,
                    "首次上传" if attempt == 0 else f"重试 {attempt}/{MAX_UPLOAD_RETRIES}",
                    timeout_ms / 1000)
        failure = "等待上传接口超时"
        valid = []
        try:
            try:
                trigger()
                deadline = time.monotonic() + timeout_ms / 1000
                while time.monotonic() < deadline:
                    if len(responses) >= file_count:
                        for response in responses:
                            validate(response)
                        valid = responses[:file_count]
                        break
                    if requests and not pending:
                        failure = "上传请求结束但未收到完整成功响应"
                        break
                    page.wait_for_timeout(100)
            except Exception as exc:
                # 原始 Playwright 异常可能携带动态 URL，不输出其原文。
                failure = f"上传失败（{type(exc).__name__}）"
            LOGGER.info("%s：核对当前资质卡片的已上传文件（上传前 %s 个）", description, baseline if baseline is not None else "未知")
            deadline = time.monotonic() + timeout_ms / 1000
            current = uploaded_count()
            while baseline is not None and current == baseline and time.monotonic() < deadline:
                page.wait_for_timeout(100)
                current = uploaded_count()
            LOGGER.info("%s：当前卡片已上传文件数 %s", description, current if current is not None else "未知")
            if baseline is not None and current == baseline + file_count:
                if pending:
                    raise PageFlowError(f"{description}：文件已出现但上传请求仍未结束，停止以避免重复上传")
                LOGGER.info("%s：已确认文件存在，上传完成%s", description,
                            "（响应异常，不重复上传）" if not valid else "")
                return valid
            if valid and baseline is None:
                # 未识别预览组件时，成功响应交由调用方现有页面校验处理。
                LOGGER.info("%s：上传接口成功，继续页面校验", description)
                return valid
            if baseline is None or current != baseline or pending:
                raise PageFlowError(f"{description}：{failure}，无法确认文件缺失或请求仍在执行，停止以避免重复上传")
            LOGGER.warning("%s：%s；当前卡片未新增文件", description, failure)
            if attempt == MAX_UPLOAD_RETRIES:
                raise PageFlowError(f"{description}：上传失败，已重试 {MAX_UPLOAD_RETRIES} 次，当前卡片仍无该文件")
        finally:
            for event, handler in handlers.items():
                page.remove_listener(event, handler)
    raise AssertionError("unreachable")
