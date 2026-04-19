"""Canonical data schemas.

Every timestamp is UTC, stored as polars Datetime[ms].
Bar-close convention: `open_time` is the bar's start; the bar covers
`[open_time, open_time + interval)` and `close_time` is inclusive of the last ms.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import polars as pl


class Interval(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def milliseconds(self) -> int:
        return _INTERVAL_MS[self]


_INTERVAL_MS: dict[Interval, int] = {
    Interval.M1: 60_000,
    Interval.M5: 300_000,
    Interval.M15: 900_000,
    Interval.M30: 1_800_000,
    Interval.H1: 3_600_000,
    Interval.H4: 14_400_000,
    Interval.D1: 86_400_000,
}


CANDLE_SCHEMA: dict[str, Any] = {
    "open_time": pl.Datetime("ms", time_zone="UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "close_time": pl.Datetime("ms", time_zone="UTC"),
    "quote_volume": pl.Float64,
    "trade_count": pl.UInt32,
    "taker_buy_base_volume": pl.Float64,
    "taker_buy_quote_volume": pl.Float64,
}


FUNDING_SCHEMA: dict[str, Any] = {
    "funding_time": pl.Datetime("ms", time_zone="UTC"),
    "funding_rate": pl.Float64,
    "mark_price": pl.Float64,
}


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: datetime
    quote_volume: float
    trade_count: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float

    def __post_init__(self) -> None:
        if self.open_time.tzinfo != UTC or self.close_time.tzinfo != UTC:
            raise ValueError("Candle timestamps must be UTC")


@dataclass(frozen=True, slots=True)
class FundingRate:
    funding_time: datetime
    funding_rate: float
    mark_price: float

    def __post_init__(self) -> None:
        if self.funding_time.tzinfo != UTC:
            raise ValueError("FundingRate.funding_time must be UTC")


def candles_to_df(candles: list[Candle]) -> pl.DataFrame:
    if not candles:
        return pl.DataFrame(schema=CANDLE_SCHEMA)
    return pl.DataFrame(
        {
            "open_time": [c.open_time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
            "close_time": [c.close_time for c in candles],
            "quote_volume": [c.quote_volume for c in candles],
            "trade_count": [c.trade_count for c in candles],
            "taker_buy_base_volume": [c.taker_buy_base_volume for c in candles],
            "taker_buy_quote_volume": [c.taker_buy_quote_volume for c in candles],
        },
        schema=CANDLE_SCHEMA,
    )


def funding_to_df(rates: list[FundingRate]) -> pl.DataFrame:
    if not rates:
        return pl.DataFrame(schema=FUNDING_SCHEMA)
    return pl.DataFrame(
        {
            "funding_time": [r.funding_time for r in rates],
            "funding_rate": [r.funding_rate for r in rates],
            "mark_price": [r.mark_price for r in rates],
        },
        schema=FUNDING_SCHEMA,
    )
