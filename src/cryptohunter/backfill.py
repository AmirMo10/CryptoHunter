"""Historical backfill orchestration.

Chunked, resumable, idempotent. Re-running a backfill over already-stored
ranges is a no-op (writes dedupe on primary timestamp).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .binance import FUNDING_LIMIT, KLINES_LIMIT, BinanceFutures
from .schemas import Interval, candles_to_df, funding_to_df
from .storage import ParquetStore

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    symbol: str
    rows_written: int
    start: datetime
    end: datetime


async def backfill_candles(
    client: BinanceFutures,
    store: ParquetStore,
    symbol: str,
    interval: Interval,
    start: datetime,
    end: datetime,
    exchange: str = "binance",
    resume: bool = True,
) -> BackfillResult:
    _check_utc_range(start, end)
    if resume:
        latest = store.latest_candle_time(exchange, symbol, interval)
        if latest is not None and latest + timedelta(milliseconds=interval.milliseconds) > start:
            start = latest + timedelta(milliseconds=interval.milliseconds)
            log.info("resume: advancing start to %s for %s %s", start, symbol, interval.value)

    if start >= end:
        log.info("nothing to backfill for %s %s (already up-to-date)", symbol, interval.value)
        return BackfillResult(symbol, 0, start, end)

    chunk_ms = KLINES_LIMIT * interval.milliseconds
    total_written = 0
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(milliseconds=chunk_ms), end)
        log.info("fetching %s %s candles [%s, %s)", symbol, interval.value, cursor, chunk_end)
        candles = await client.klines(symbol, interval, cursor, chunk_end)
        if not candles:
            cursor = chunk_end
            continue

        df = candles_to_df(candles)
        total_written += store.write_candles(exchange, symbol, interval, df)

        last_open = candles[-1].open_time
        next_cursor = last_open + timedelta(milliseconds=interval.milliseconds)
        cursor = max(next_cursor, chunk_end) if len(candles) < KLINES_LIMIT else next_cursor

    return BackfillResult(symbol, total_written, start, end)


async def backfill_funding(
    client: BinanceFutures,
    store: ParquetStore,
    symbol: str,
    start: datetime,
    end: datetime,
    exchange: str = "binance",
    resume: bool = True,
) -> BackfillResult:
    _check_utc_range(start, end)
    if resume:
        latest = store.latest_funding_time(exchange, symbol)
        if latest is not None and latest >= start:
            start = latest + timedelta(milliseconds=1)
            log.info("resume: advancing funding start to %s for %s", start, symbol)

    if start >= end:
        return BackfillResult(symbol, 0, start, end)

    total_written = 0
    cursor = start
    chunk_ms = FUNDING_LIMIT * 8 * 3_600_000
    while cursor < end:
        chunk_end = min(cursor + timedelta(milliseconds=chunk_ms), end)
        log.info("fetching %s funding [%s, %s)", symbol, cursor, chunk_end)
        rates = await client.funding_rates(symbol, cursor, chunk_end)
        if not rates:
            cursor = chunk_end
            continue

        df = funding_to_df(rates)
        total_written += store.write_funding(exchange, symbol, df)

        last_time = rates[-1].funding_time
        next_cursor = last_time + timedelta(milliseconds=1)
        cursor = max(next_cursor, chunk_end) if len(rates) < FUNDING_LIMIT else next_cursor

    return BackfillResult(symbol, total_written, start, end)


def _check_utc_range(start: datetime, end: datetime) -> None:
    if start.tzinfo != UTC or end.tzinfo != UTC:
        raise ValueError("start and end must be UTC")
    if start >= end:
        raise ValueError(f"start ({start}) must be strictly before end ({end})")
