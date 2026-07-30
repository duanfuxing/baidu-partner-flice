from __future__ import annotations

import pytest

from src.api_client import BaiduApiClient, RetryConfig
from src.errors import AuthenticationRequired, BusinessError


class FakeResponse:
    def __init__(self, body, status: int = 200):
        self.body = body
        self.status = status

    def json(self):
        return self.body


class FakeRequest:
    def __init__(self, post_response=None, get_response=None):
        self.post_response = post_response
        self.get_response = get_response
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_response

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_response


def test_search_company_extracts_unique_cust_id() -> None:
    request = FakeRequest(
        post_response=FakeResponse({"code": 0, "data": {"totalCount": 1, "result": [{"custId": "58400710"}]}})
    )

    cust_id = BaiduApiClient(request).search_company("示例公司")

    assert cust_id == "58400710"
    payload = request.post_calls[0][1]["data"]
    assert payload["custName"] == "示例公司"
    assert payload["isAgentPlatform"] is True


@pytest.mark.parametrize("total_count", [0, 2])
def test_search_company_rejects_non_unique_results(total_count: int) -> None:
    request = FakeRequest(
        post_response=FakeResponse(
            {"code": 0, "data": {"totalCount": total_count, "result": ([] if total_count == 0 else [{"custId": "1"}, {"custId": "2"}])}}
        )
    )

    with pytest.raises(BusinessError):
        BaiduApiClient(request).search_company("示例公司")


def test_get_qualification_url_uses_cust_id_query() -> None:
    request = FakeRequest(
        get_response=FakeResponse({"code": 0, "data": {"qulificationAuditUrl": " http://example.com/flice "}})
    )

    url = BaiduApiClient(request).get_qualification_url("58400710")

    assert url == "http://example.com/flice"
    assert request.get_calls[0][1]["params"] == {"custId": "58400710"}


def test_api_client_raises_authentication_error() -> None:
    request = FakeRequest(post_response=FakeResponse({}, status=401))

    with pytest.raises(AuthenticationRequired):
        BaiduApiClient(request).search_company("示例公司")


def test_api_client_retries_server_error() -> None:
    class RetryRequest(FakeRequest):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def post(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse({}, status=500)
            return FakeResponse({"code": 0, "data": {"totalCount": 1, "result": [{"custId": "1"}]}})

    request = RetryRequest()
    client = BaiduApiClient(request, RetryConfig(attempts=2, backoff_seconds=0))

    assert client.search_company("示例公司") == "1"
    assert request.calls == 2
