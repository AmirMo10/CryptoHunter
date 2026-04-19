"""Data-quality checks. Gaps in a time series are almost never legitimate
on liquid perps - flag them loudly rather than silently passing through.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import cast

import polars as pl

from .schemas import Interval


@dataclass(frozen=True, slots=True)
class Gap:
    start: datetime
    end: datetime
    missing_bars: int

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


def find_candle_gaps(df: pl.DataFrame, interval: Interval) -> list[Gap]:
    """Return gaps where consecutive `open_time` values are further apart than
    one interval. `end` is the open_time of the row AFTER the gap (exclusive).
    """
    if df.height < 2:
        return []

    step_ms = interval.milliseconds
    ts = df.sort("open_time").get_column("open_time").to_list()
    gaps: list[Gap] = []
    for prev, curr in pairwise(ts):
        delta_ms = int((curr - prev).total_seconds() * 1000)
        if delta_ms > step_ms:
            missing = delta_ms // step_ms - 1
            gaps.append(
                Gap(
                    start=prev + timedelta(milliseconds=step_ms),
                    end=curr,
                    missing_bars=missing,
                )
            )
    return gaps


def find_duplicate_timestamps(df: pl.DataFrame, ts_col: str) -> int:
    if df.is_empty():
        return 0
    unique_count = cast(int, df.select(pl.col(ts_col).n_unique()).item())
    return df.height - unique_count


def check_monotonic(df: pl.DataFrame, ts_col: str) -> bool:
    if df.height < 2:
        return True
    min_delta = df.get_column(ts_col).diff().drop_nulls().min()
    if min_delta is None:
        return True
    return cast(timedelta, min_delta) > timedelta(0)


@dataclass(frozen=True, slots=True)
class CandleQualityReport:
    rows: int
    first_ts: datetime | None
    last_ts: datetime | None
    gaps: list[Gap]
    duplicates: int
    monotonic: bool

    @property
    def ok(self) -> bool:
        return not self.gaps and self.duplicates == 0 and self.monotonic

    def summary(self) -> str:
        return (
            f"rows={self.rows} first={self.first_ts} last={self.last_ts} "
            f"gaps={len(self.gaps)} missing_bars={sum(g.missing_bars for g in self.gaps)} "
            f"duplicates={self.duplicates} monotonic={self.monotonic}"
        )


def audit_candles(df: pl.DataFrame, interval: Interval) -> CandleQualityReport:
    if df.is_empty():
        return CandleQualityReport(
            rows=0, first_ts=None, last_ts=None, gaps=[], duplicates=0, monotonic=True
        )
    return CandleQualityReport(
        rows=df.height,
        first_ts=cast(datetime, df.select(pl.col("open_time").min()).item()),
        last_ts=cast(datetime, df.select(pl.col("open_time").max()).item()),
        gaps=find_candle_gaps(df, interval),
        duplicates=find_duplicate_timestamps(df, "open_time"),
        monotonic=check_monotonic(df, "open_time"),
    )
