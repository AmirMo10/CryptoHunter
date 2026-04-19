from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from cryptohunter import backfill as bf
from cryptohunter.backfill import backfill_candles, backfill_funding
from cryptohunter.exchanges.binance import BinanceFutures
from cryptohunter.schemas import Interval
from cryptohunter.storage import ParquetStore

from .conftest import utc


def _kline_row(open_ms: int) -> list:
    return [
        open_ms,
        "99",
        "102",
        "97",
        "100",
        "10.0",
        open_ms + 59_999,
        "1000.0",
        50,
        "5.0",
        "500.0",
        "0",
    ]


def _funding_row(ts_ms: int) -> dict:
    return {
        "symbol": "BTCUSDT",
        "fundingTime": ts_ms,
        "fundingRate": "0.0001",
        "markPrice": "50000.0",
    }


async def test_backfill_candles_writes_and_resumes(
    tmp_store_dir: Path, httpx_mock: HTTPXMock
) -> None:
    start = utc(2024, 1, 1)
    end = utc(2024, 1, 1, 0, 5)

    httpx_mock.add_response(
        json=[_kline_row(int(start.timestamp() * 1000) + i * 60_000) for i in range(5)]
    )

    async with BinanceFutures(request_pause_s=0) as client:
        store = ParquetStore(tmp_store_dir)
        result = await backfill_candles(client, store, "BTCUSDT", Interval.M1, start, end)

    assert result.rows_written == 5
    df = store.read_candles("binance", "BTCUSDT", Interval.M1)
    assert df.height == 5

    async with BinanceFutures(request_pause_s=0) as client:
        store = ParquetStore(tmp_store_dir)
        result = await backfill_candles(client, store, "BTCUSDT", Interval.M1, start, end)

    assert result.rows_written == 0


async def test_backfill_candles_chunks_over_limit(
    tmp_store_dir: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bf, "KLINES_LIMIT", 3)

    start = utc(2024, 1, 1)
    end = start + timedelta(minutes=7)

    first = [_kline_row(int(start.timestamp() * 1000) + i * 60_000) for i in range(3)]
    second = [_kline_row(int(start.timestamp() * 1000) + (3 + i) * 60_000) for i in range(3)]
    third = [_kline_row(int(start.timestamp() * 1000) + 6 * 60_000)]

    httpx_mock.add_response(json=first)
    httpx_mock.add_response(json=second)
    httpx_mock.add_response(json=third)

    async with BinanceFutures(request_pause_s=0) as client:
        store = ParquetStore(tmp_store_dir)
        result = await backfill_candles(client, store, "BTCUSDT", Interval.M1, start, end)

    assert result.rows_written == 7


async def test_backfill_funding(tmp_store_dir: Path, httpx_mock: HTTPXMock) -> None:
    start = utc(2024, 1, 1)
    end = utc(2024, 1, 2)
    rows = [_funding_row(int(start.timestamp() * 1000) + i * 8 * 3_600_000) for i in range(3)]
    httpx_mock.add_response(json=rows)

    async with BinanceFutures(request_pause_s=0) as client:
        store = ParquetStore(tmp_store_dir)
        result = await backfill_funding(client, store, "BTCUSDT", start, end)

    assert result.rows_written == 3
    df = store.read_funding("binance", "BTCUSDT")
    assert df.height == 3
