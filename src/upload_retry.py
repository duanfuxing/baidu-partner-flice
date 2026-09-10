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
    """成功响应与预览分别核验；仅明确失败且无新增文件时重试。"""
    baseline = uploaded_count()
    for attempt in range(MAX_UPLOAD_RETRIES + 1):
        requests, pending, responses = set(), set(), []
        failed_requests = set()

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

        def on_failed(request):
            if request in requests:
                failed_requests.add(request)
            pending.discard(request)

        handlers = {"request": on_request, "response": on_response,
                    "requestfinished": on_finished, "requestfailed": on_failed}
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
                    if len(responses) >= file_count and not pending:
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
            while (baseline is not None
                   and (current is None or current < baseline + file_count or pending)
                   and time.monotonic() < deadline):
                page.wait_for_timeout(100)
                current = uploaded_count()
            # 等待回填期间仍可能收到响应，最后逐项保留成功凭据。
            for response in responses:
                try:
                    validate(response)
                except Exception:
                    failure = f"上传响应校验失败（HTTP {response.status}）"
                else:
                    valid.append(response)
            LOGGER.info("%s：当前卡片已上传文件数 %s", description, current if current is not None else "未知")
            if baseline is not None and current == baseline + file_count:
                if pending:
                    raise PageFlowError(f"{description}：文件已出现但上传请求仍未结束，停止以避免重复上传")
                if len(valid) != file_count or failed_requests:
                    raise PageFlowError(f"{description}：页面已有文件但缺少完整成功上传凭据，停止，不重复上传")
                LOGGER.info("%s：上传响应与页面文件数量均已确认", description)
                return valid
            if len(valid) == file_count and baseline is None and not pending and not failed_requests:
                # 未识别预览组件时，成功响应交由调用方现有页面校验处理。
                LOGGER.info("%s：上传接口成功，继续页面校验", description)
                return valid
            if valid:
                raise PageFlowError(
                    f"{description}：已有 {len(valid)}/{file_count} 个成功上传响应，"
                    f"但页面文件未完整回填（上传前 {baseline}，当前 {current}），停止，不重复上传"
                )
            if baseline is None or current != baseline or pending:
                raise PageFlowError(f"{description}：{failure}，无法确认文件缺失或请求仍在执行，停止以避免重复上传")
            if (failed_requests or len(requests) != file_count
                    or len(responses) != file_count
                    or not all(500 <= response.status < 600 for response in responses)):
                raise PageFlowError(f"{description}：{failure}，上传结果未知或不可重试，停止，不重复上传")
            LOGGER.warning("%s：%s；当前卡片未新增文件", description, failure)
            if attempt == MAX_UPLOAD_RETRIES:
                raise PageFlowError(f"{description}：上传失败，已重试 {MAX_UPLOAD_RETRIES} 次，当前卡片仍无该文件")
        finally:
            for event, handler in handlers.items():
                page.remove_listener(event, handler)
    raise AssertionError("unreachable")
