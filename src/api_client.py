"""百度客户接口客户端。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import ApiError, AuthenticationRequired, BusinessError

SEARCH_URL = "https://partner.baidu.com/polaris-web/onecrm-oneFrontArchive/archive/cust/list/query"
QUALIFICATION_SUMMARY_URL = "https://partner.baidu.com/polaris-web/onecrm-oneFrontArchive/archive/cust/summary/query"


class ApiResponse(Protocol):
    status: int

    def json(self) -> Any: ...


class ApiRequestContext(Protocol):
    def post(self, url: str, **kwargs: Any) -> ApiResponse: ...

    def get(self, url: str, **kwargs: Any) -> ApiResponse: ...


@dataclass(frozen=True)
class RetryConfig:
    attempts: int = 3
    backoff_seconds: float = 0.5


class BaiduApiClient:
    """使用 Playwright 浏览器上下文中的请求客户端调用百度接口。"""

    def __init__(self, request: ApiRequestContext, retry: RetryConfig | None = None) -> None:
        self.request = request
        self.retry = retry or RetryConfig()

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retry.attempts + 1):
            try:
                response = getattr(self.request, method)(url, **kwargs)
                if response.status in (401, 403):
                    raise AuthenticationRequired(f"接口返回未授权状态：HTTP {response.status}")
                if response.status >= 500:
                    raise ApiError(f"接口服务异常：HTTP {response.status}")
                if response.status >= 400:
                    raise ApiError(f"接口请求失败：HTTP {response.status}")
                body = response.json()
                if not isinstance(body, dict):
                    raise ApiError("接口响应不是 JSON 对象")
                return body
            except AuthenticationRequired:
                raise
            except Exception as exc:  # 网络异常和 5xx 在有限次数内重试
                last_error = exc
                if attempt == self.retry.attempts:
                    break
                time.sleep(self.retry.backoff_seconds * attempt)
        raise ApiError(f"接口调用失败：{last_error}") from last_error

    @staticmethod
    def _check_success(body: dict[str, Any], operation: str) -> dict[str, Any]:
        if body.get("code") != 0:
            message = body.get("msg") or "未知业务错误"
            raise BusinessError(f"{operation}失败：{message}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise ApiError(f"{operation}响应缺少 data 对象")
        return data

    def search_company(self, company_name: str) -> str:
        payload = {
            "custName": company_name,
            "url": "",
            "urlBindAgentIds": [],
            "urlBindAgentUsers": [],
            "queryType": 2,
            "orderMap": {"name": "siteAddTime", "order": 0},
            "isAgentPlatform": True,
            "statusCategory": 0,
            "pageNum": 1,
            "pageSize": 20,
            "total": 1,
            "pageIndex": 1,
        }
        body = self._request(
            "post",
            SEARCH_URL,
            data=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        data = self._check_success(body, "公司搜索")
        try:
            total_count = int(data["totalCount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("公司搜索响应缺少有效的 data.totalCount") from exc
        results = data.get("result")
        if not isinstance(results, list):
            raise ApiError("公司搜索响应缺少 data.result 数组")
        if total_count == 0:
            raise BusinessError(f"公司不存在：{company_name}")
        if total_count != 1 or len(results) != 1:
            raise BusinessError(f"公司搜索结果不唯一：{company_name}，结果数为 {total_count}")
        cust_id = results[0].get("custId")
        if cust_id is None or str(cust_id).strip() == "":
            raise ApiError("公司搜索结果缺少 custId")
        return str(cust_id)

    def get_qualification_url(self, cust_id: str) -> str:
        body = self._request(
            "get",
            QUALIFICATION_SUMMARY_URL,
            params={"custId": cust_id},
            headers={"Accept": "application/json"},
        )
        data = self._check_success(body, "获取资质链接")
        qualification_url = data.get("qulificationAuditUrl")
        if not isinstance(qualification_url, str) or not qualification_url.strip():
            raise ApiError("获取资质链接响应缺少 qulificationAuditUrl")
        return qualification_url.strip()
