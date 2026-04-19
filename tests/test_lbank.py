"""LBank REST client tests (public endpoints + error envelope handling)."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from cryptohunter.exchanges.lbank import (
    BASE_URL,
    PRV_PREFIX,
    PUB_PREFIX,
    LBankContract,
    LBankError,
    LBankHTTPError,
)


def _envelope(data: object, *, result: bool = True, error_code: str = "0", msg: str = "") -> dict:
    return {"result": result, "error_code": error_code, "msg": msg, "data": data, "success": result}


async def test_get_time_returns_int(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/getTime",
        json=_envelope(1_700_000_000_000),
    )
    async with LBankContract(request_pause_s=0) as c:
        ts = await c.get_time()
    assert ts == 1_700_000_000_000


async def test_get_time_accepts_dict_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/getTime",
        json=_envelope({"timestamp": 1_700_000_000_000}),
    )
    async with LBankContract(request_pause_s=0) as c:
        ts = await c.get_time()
    assert ts == 1_700_000_000_000


async def test_instruments_passes_product_group(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/instrument?productGroup=SwapU",
        json=_envelope([{"symbol": "BTCUSDT", "tickSize": "0.1"}]),
    )
    async with LBankContract(request_pause_s=0) as c:
        rows = await c.instruments()
    assert rows[0]["symbol"] == "BTCUSDT"


async def test_market_data_returns_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/marketData?productGroup=SwapU",
        json=_envelope(
            [
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "50000",
                    "prePositionFeeRate": "0.0001",
                }
            ]
        ),
    )
    async with LBankContract(request_pause_s=0) as c:
        snap = await c.market_data()
    assert snap[0]["prePositionFeeRate"] == "0.0001"


async def test_market_order_returns_orderbook(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/marketOrder?symbol=BTCUSDT&depth=10",
        json=_envelope({"bids": [["50000", "1.0"]], "asks": [["50001", "1.0"]]}),
    )
    async with LBankContract(request_pause_s=0) as c:
        book = await c.market_order("BTCUSDT")
    assert book["bids"][0] == ["50000", "1.0"]


async def test_business_error_raises_lbank_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/instrument?productGroup=SwapU",
        json=_envelope(None, result=False, error_code="8", msg="product does not exist"),
    )
    async with LBankContract(request_pause_s=0) as c:
        with pytest.raises(LBankError) as exc_info:
            await c.instruments()
    assert exc_info.value.code == "8"
    assert "product does not exist" in str(exc_info.value)


async def test_fatal_error_code_short_circuits_retries(httpx_mock: HTTPXMock) -> None:
    # 178 = API key limit exceeded — retrying makes it worse.
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/getTime",
        json=_envelope(None, result=False, error_code="178", msg="rate limit hit"),
    )
    async with LBankContract(request_pause_s=0, max_retries=5) as c:
        with pytest.raises(LBankError, match="178"):
            await c.get_time()


async def test_retryable_error_code_eventually_succeeds(httpx_mock: HTTPXMock) -> None:
    # 10012 = request too frequent; client should back off and retry.
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/getTime",
        json=_envelope(None, result=False, error_code="10012", msg="too frequent"),
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/getTime",
        json=_envelope(1_700_000_000_000),
    )
    async with LBankContract(request_pause_s=0, max_retries=3) as c:
        ts = await c.get_time()
    assert ts == 1_700_000_000_000


async def test_http_5xx_retries(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=500, text="upstream")
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/getTime",
        json=_envelope(1_700_000_000_000),
    )
    async with LBankContract(request_pause_s=0, max_retries=3) as c:
        assert await c.get_time() == 1_700_000_000_000


async def test_http_4xx_surfaces(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=404, text="not found")
    async with LBankContract(request_pause_s=0) as c:
        with pytest.raises(LBankHTTPError, match="HTTP 404"):
            await c.get_time()


async def test_private_endpoints_without_keys_raise() -> None:
    async with LBankContract(request_pause_s=0) as c:
        with pytest.raises(NotImplementedError):
            await c.account()
        with pytest.raises(NotImplementedError):
            await c.place_order()


async def test_string_result_field_parses(httpx_mock: HTTPXMock) -> None:
    # Some LBank endpoints return result as the string "true"/"false".
    httpx_mock.add_response(
        url=f"{BASE_URL}{PUB_PREFIX}/getTime",
        json={"result": "true", "error_code": "0", "msg": "", "data": 1_700_000_000_000},
    )
    async with LBankContract(request_pause_s=0) as c:
        assert await c.get_time() == 1_700_000_000_000


async def test_private_call_attaches_signed_headers(httpx_mock: HTTPXMock) -> None:
    """Spot-check the signing pipeline: private request must carry the three headers."""
    httpx_mock.add_response(
        method="GET",
        json=_envelope({"asset": "USDT", "balance": "0"}),
    )
    async with LBankContract(api_key="test-key", secret_key="test-secret", request_pause_s=0) as c:
        data = await c._private("GET", f"{PRV_PREFIX}/account", {"asset": "USDT"})
    assert data == {"asset": "USDT", "balance": "0"}
    req = httpx_mock.get_requests()[-1]
    assert req.headers["signature_method"] == "HmacSHA256"
    assert "timestamp" in req.headers
    assert 30 <= len(req.headers["echostr"]) <= 40
    # All signed params should be in the query string, including sign.
    assert "sign=" in str(req.url)
    assert "api_key=test-key" in str(req.url)
