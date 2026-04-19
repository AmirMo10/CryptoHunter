from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryptohunter.schemas import Candle, FundingRate


def utc(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def make_candle(open_time: datetime, close: float = 100.0, interval_ms: int = 60_000) -> Candle:
    return Candle(
        open_time=open_time,
        open=close - 1,
        high=close + 2,
        low=close - 3,
        close=close,
        volume=10.0,
        close_time=open_time + timedelta(milliseconds=interval_ms - 1),
        quote_volume=1000.0,
        trade_count=50,
        taker_buy_base_volume=5.0,
        taker_buy_quote_volume=500.0,
    )


def make_funding(ts: datetime, rate: float = 0.0001, mark: float = 50_000.0) -> FundingRate:
    return FundingRate(funding_time=ts, funding_rate=rate, mark_price=mark)


@pytest.fixture
def tmp_store_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"
