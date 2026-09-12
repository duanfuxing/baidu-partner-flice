"""只恢复页面生成的资质详情 GET，将最终响应交回页面正常渲染。"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from .errors import AuthenticationRequired, PageFlowError

LOGGER = logging.getLogger(__name__)
DETAIL_PATTERN = re.compile(r'^https?://fkzhunru\.baidu\.com/permit/web/permit/(?:geturlinfo|geturlandproductinfo)(?:\?|$)')


class DetailReadRecovery:
    def __init__(self, page, timeout):
        self.page = page
        self.attempt_timeout = max(1, min(10_000, timeout // 3))
        self.pending = 0
        self.last_finished = 0.0
        self.unauthorized = False
        self.failures = {}
        page.route(DETAIL_PATTERN, self.handle)

    def raise_if_unauthorized(self):
        if self.unauthorized:
            raise AuthenticationRequired('资质详情读取未授权，请重新登录')

    def raise_if_failed(self):
        self.raise_if_unauthorized()
        if self.failures and not self.pending:
            raise PageFlowError(next(iter(self.failures.values())))

    def handle(self, route):
        request = route.request
        if request.method != 'GET' or not DETAIL_PATTERN.match(request.url):
            route.fallback()
            return
        endpoint = urlsplit(request.url).path.rsplit('/', 1)[-1]
        self.pending += 1
        try:
            for attempt in range(2):
                try:
                    # 不构造 URL、请求头或认证参数；保留原页面请求。
                    response = route.fetch(timeout=self.attempt_timeout, max_redirects=0, max_retries=0)
                except PlaywrightError:
                    if attempt:
                        self.failures[endpoint] = f'资质详情读取[{endpoint}]重试后仍未完成，未使用空列表或重放保存'
                        LOGGER.error('资质详情读取[%s]：两次读取均未完成，未重放任何保存请求', endpoint)
                        route.abort('failed')
                        return
                    LOGGER.warning('资质详情读取[%s]：网络读取未完成，只读重试1/1', endpoint)
                    continue
                try:
                    try:
                        body = response.json()
                    except Exception:
                        body = None
                    status = body.get('status') if isinstance(body, dict) else None
                    if response.status in (401, 403):
                        self.unauthorized = True
                    retryable = (500 <= response.status < 600 or
                                 response.status == 200 and type(status) is int and status == 1009)
                    if retryable and not attempt:
                        LOGGER.warning('资质详情读取[%s]：HTTP %s，status=%s，只读重试1/1',
                                       endpoint, response.status, status if type(status) is int else 'invalid')
                        continue
                    LOGGER.info('资质详情读取[%s]：HTTP %s，status=%s%s', endpoint, response.status,
                                status if type(status) is int else 'invalid', '（重试后）' if attempt else '')
                    if (response.status != 200 or type(status) is not int or status != 0
                            or not isinstance(body.get('data') if isinstance(body, dict) else None, dict)):
                        self.failures[endpoint] = (f'资质详情读取[{endpoint}]失败（HTTP {response.status}，'
                                                   f'status={status if type(status) is int else "invalid"}），未使用空列表或重放保存')
                    else:
                        self.failures.pop(endpoint, None)
                    route.fulfill(response=response)
                    return
                finally:
                    response.dispose()
        finally:
            self.pending -= 1
            self.last_finished = time.monotonic()
