from __future__ import annotations

from datetime import datetime

import pytest
from pytest_httpx import HTTPXMock

from cryptohunter.binance import BASE_URL, BinanceFutures, BinanceFuturesError
from cryptohunter.schemas import Interval

from .conftest import utc


def _kline_row(open_ms: int, close: float = 100.0) -> list:
    return [
        open_ms,
        str(close - 1),
        str(close + 2),
        str(close - 3),
        str(close),
        "10.0",
        open_ms + 59_999,
        "1000.0",
        50,
        "5.0",
        "500.0",
        "0",
    ]


def _funding_row(ts_ms: int, rate: str = "0.0001") -> dict:
    return {"symbol": "BTCUSDT", "fundingTime": ts_ms, "fundingRate": rate, "markPrice": "50000.0"}


async def test_klines_parses_response(httpx_mock: HTTPXMock) -> None:
    start = utc(2024, 1, 1)
    end = utc(2024, 1, 1, 0, 3)
    httpx_mock.add_response(
        url=(
            f"{BASE_URL}/fapi/v1/klines?"
            f"symbol=BTCUSDT&interval=1m&startTime={int(start.timestamp() * 1000)}"
            f"&endTime={int(end.timestamp() * 1000) - 1}&limit=1500"
        ),
        json=[_kline_row(int(start.timestamp() * 1000) + i * 60_000) for i in range(3)],
    )
    async with BinanceFutures(request_pause_s=0) as client:
        candles = await client.klines("BTCUSDT", Interval.M1, start, end)
    assert len(candles) == 3
    assert candles[0].open_time == start
    assert candles[0].close == 100.0


async def test_funding_rates_parses_response(httpx_mock: HTTPXMock) -> None:
    start = utc(2024, 1, 1)
    end = utc(2024, 1, 2)
    httpx_mock.add_response(
        url=(
            f"{BASE_URL}/fapi/v1/fundingRate?"
            f"symbol=BTCUSDT&startTime={int(start.timestamp() * 1000)}"
            f"&endTime={int(end.timestamp() * 1000) - 1}&limit=1000"
        ),
        json=[_funding_row(int(start.timestamp() * 1000) + i * 8 * 3_600_000) for i in range(3)],
    )
    async with BinanceFutures(request_pause_s=0) as client:
        rates = await client.funding_rates("BTCUSDT", start, end)
    assert len(rates) == 3
    assert rates[0].funding_rate == 0.0001


async def test_rejects_naive_timestamps() -> None:
    async with BinanceFutures(request_pause_s=0) as client:
        with pytest.raises(ValueError, match="UTC"):
            await client.klines("BTCUSDT", Interval.M1, datetime(2024, 1, 1), datetime(2024, 1, 2))


async def test_retries_on_500(httpx_mock: HTTPXMock) -> None:
    start = utc(2024, 1, 1)
    end = utc(2024, 1, 1, 0, 1)
    httpx_mock.add_response(status_code=500, text="upstream")
    httpx_mock.add_response(
        json=[_kline_row(int(start.timestamp() * 1000))],
    )
    async with BinanceFutures(request_pause_s=0) as client:
        candles = await client.klines("BTCUSDT", Interval.M1, start, end)
    assert len(candles) == 1


async def test_surfaces_4xx_errors(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=400, text="bad symbol")
    async with BinanceFutures(request_pause_s=0) as client:
        with pytest.raises(BinanceFuturesError, match="HTTP 400"):
            await client.klines("BADSYM", Interval.M1, utc(2024, 1, 1), utc(2024, 1, 1, 0, 1))
