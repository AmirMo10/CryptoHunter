from __future__ import annotations

from datetime import datetime

import pytest

from cryptohunter.schemas import Candle, FundingRate, Interval, candles_to_df, funding_to_df

from .conftest import make_candle, make_funding, utc


def test_interval_milliseconds() -> None:
    assert Interval.M1.milliseconds == 60_000
    assert Interval.H1.milliseconds == 3_600_000
    assert Interval.D1.milliseconds == 86_400_000


def test_candle_requires_utc() -> None:
    naive = datetime(2024, 1, 1)
    with pytest.raises(ValueError, match="UTC"):
        Candle(
            open_time=naive,
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
            close_time=naive,
            quote_volume=1,
            trade_count=1,
            taker_buy_base_volume=1,
            taker_buy_quote_volume=1,
        )


def test_funding_requires_utc() -> None:
    with pytest.raises(ValueError, match="UTC"):
        FundingRate(funding_time=datetime(2024, 1, 1), funding_rate=0.0, mark_price=0.0)


def test_candles_to_df_empty() -> None:
    df = candles_to_df([])
    assert df.is_empty()
    assert "open_time" in df.columns


def test_candles_to_df_roundtrip() -> None:
    candles = [make_candle(utc(2024, 1, 1, h)) for h in range(3)]
    df = candles_to_df(candles)
    assert df.height == 3
    assert df["open_time"].dtype.time_zone == "UTC"
    assert df["close"].to_list() == [100.0, 100.0, 100.0]


def test_funding_to_df() -> None:
    rates = [make_funding(utc(2024, 1, 1, h * 8)) for h in range(3)]
    df = funding_to_df(rates)
    assert df.height == 3
    assert df["funding_rate"].to_list() == [0.0001, 0.0001, 0.0001]
