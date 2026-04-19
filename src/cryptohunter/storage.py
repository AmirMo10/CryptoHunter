"""Parquet storage partitioned by exchange/symbol/date.

Layout:
  {root}/candles/exchange={ex}/symbol={sym}/interval={iv}/date={YYYY-MM-DD}/data.parquet
  {root}/funding/exchange={ex}/symbol={sym}/date={YYYY-MM-DD}/data.parquet

Daily partitioning keeps individual files small (even 1m candles are ~1440 rows/day)
and allows parallel reads over date ranges via polars' scan_parquet.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from .schemas import CANDLE_SCHEMA, FUNDING_SCHEMA, Interval


class ParquetStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _candles_dir(self, exchange: str, symbol: str, interval: Interval, day: date) -> Path:
        return (
            self.root
            / "candles"
            / f"exchange={exchange}"
            / f"symbol={symbol}"
            / f"interval={interval.value}"
            / f"date={day.isoformat()}"
        )

    def _funding_dir(self, exchange: str, symbol: str, day: date) -> Path:
        return (
            self.root
            / "funding"
            / f"exchange={exchange}"
            / f"symbol={symbol}"
            / f"date={day.isoformat()}"
        )

    def write_candles(
        self, exchange: str, symbol: str, interval: Interval, df: pl.DataFrame
    ) -> int:
        if df.is_empty():
            return 0
        _require_schema(df, CANDLE_SCHEMA)
        df = df.sort("open_time").unique(subset=["open_time"], keep="last")
        written = 0
        for day, part in _partition_by_day(df, "open_time"):
            out_dir = self._candles_dir(exchange, symbol, interval, day)
            written += _merge_and_write(out_dir, part, key="open_time")
        return written

    def write_funding(self, exchange: str, symbol: str, df: pl.DataFrame) -> int:
        if df.is_empty():
            return 0
        _require_schema(df, FUNDING_SCHEMA)
        df = df.sort("funding_time").unique(subset=["funding_time"], keep="last")
        written = 0
        for day, part in _partition_by_day(df, "funding_time"):
            out_dir = self._funding_dir(exchange, symbol, day)
            written += _merge_and_write(out_dir, part, key="funding_time")
        return written

    def read_candles(
        self,
        exchange: str,
        symbol: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        base = (
            self.root
            / "candles"
            / f"exchange={exchange}"
            / f"symbol={symbol}"
            / f"interval={interval.value}"
        )
        return _scan_range(base, "open_time", start, end, CANDLE_SCHEMA)

    def read_funding(
        self,
        exchange: str,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        base = self.root / "funding" / f"exchange={exchange}" / f"symbol={symbol}"
        return _scan_range(base, "funding_time", start, end, FUNDING_SCHEMA)

    def latest_candle_time(self, exchange: str, symbol: str, interval: Interval) -> datetime | None:
        df = self.read_candles(exchange, symbol, interval)
        if df.is_empty():
            return None
        return cast(datetime, df.select(pl.col("open_time").max()).item())

    def latest_funding_time(self, exchange: str, symbol: str) -> datetime | None:
        df = self.read_funding(exchange, symbol)
        if df.is_empty():
            return None
        return cast(datetime, df.select(pl.col("funding_time").max()).item())


def _require_schema(df: pl.DataFrame, expected: dict[str, Any]) -> None:
    missing = set(expected) - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing columns: {sorted(missing)}")


def _partition_by_day(df: pl.DataFrame, ts_col: str) -> Iterator[tuple[date, pl.DataFrame]]:
    with_day = df.with_columns(pl.col(ts_col).dt.date().alias("_day"))
    for (day,), part in with_day.group_by("_day", maintain_order=True):
        yield cast(date, day), part.drop("_day")


def _merge_and_write(out_dir: Path, new_df: pl.DataFrame, key: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data.parquet"
    if out_path.exists():
        existing = pl.read_parquet(out_path)
        combined = pl.concat([existing, new_df]).unique(subset=[key], keep="last").sort(key)
    else:
        combined = new_df
    combined.write_parquet(out_path, compression="zstd")
    return new_df.height


def _scan_range(
    base: Path,
    ts_col: str,
    start: datetime | None,
    end: datetime | None,
    schema: dict[str, Any],
) -> pl.DataFrame:
    if not base.exists():
        return pl.DataFrame(schema=schema)
    files = sorted(base.glob("date=*/data.parquet"))
    if not files:
        return pl.DataFrame(schema=schema)
    lf = pl.scan_parquet([str(f) for f in files])
    if start is not None:
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        lf = lf.filter(pl.col(ts_col) >= start)
    if end is not None:
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        lf = lf.filter(pl.col(ts_col) < end)
    return lf.sort(ts_col).collect()
