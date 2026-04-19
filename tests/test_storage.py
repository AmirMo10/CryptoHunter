from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from cryptohunter.schemas import Interval, candles_to_df, funding_to_df
from cryptohunter.storage import ParquetStore

from .conftest import make_candle, make_funding, utc


def test_write_and_read_candles(tmp_store_dir: Path) -> None:
    store = ParquetStore(tmp_store_dir)
    candles = [make_candle(utc(2024, 1, 1, h=0) + timedelta(minutes=i)) for i in range(5)]
    df = candles_to_df(candles)

    n = store.write_candles("binance", "BTCUSDT", Interval.M1, df)
    assert n == 5

    read = store.read_candles("binance", "BTCUSDT", Interval.M1)
    assert read.height == 5
    assert read["open_time"].to_list() == df["open_time"].to_list()


def test_write_candles_partitions_by_day(tmp_store_dir: Path) -> None:
    store = ParquetStore(tmp_store_dir)
    candles = [make_candle(utc(2024, 1, 1, 23, 59)), make_candle(utc(2024, 1, 2, 0, 0))]
    df = candles_to_df(candles)
    store.write_candles("binance", "BTCUSDT", Interval.M1, df)

    parts = sorted((tmp_store_dir / "candles").rglob("data.parquet"))
    assert len(parts) == 2
    assert any("date=2024-01-01" in str(p) for p in parts)
    assert any("date=2024-01-02" in str(p) for p in parts)


def test_write_candles_is_idempotent(tmp_store_dir: Path) -> None:
    store = ParquetStore(tmp_store_dir)
    candles = [make_candle(utc(2024, 1, 1) + timedelta(minutes=i)) for i in range(3)]
    df = candles_to_df(candles)

    store.write_candles("binance", "BTCUSDT", Interval.M1, df)
    store.write_candles("binance", "BTCUSDT", Interval.M1, df)

    read = store.read_candles("binance", "BTCUSDT", Interval.M1)
    assert read.height == 3


def test_write_candles_dedupes_across_partials(tmp_store_dir: Path) -> None:
    store = ParquetStore(tmp_store_dir)
    first = candles_to_df(
        [make_candle(utc(2024, 1, 1) + timedelta(minutes=i), close=100.0) for i in range(3)]
    )
    overlap = candles_to_df(
        [make_candle(utc(2024, 1, 1) + timedelta(minutes=i), close=999.0) for i in range(2, 5)]
    )

    store.write_candles("binance", "BTCUSDT", Interval.M1, first)
    store.write_candles("binance", "BTCUSDT", Interval.M1, overlap)

    read = store.read_candles("binance", "BTCUSDT", Interval.M1)
    assert read.height == 5
    closes = read.sort("open_time")["close"].to_list()
    assert closes == [100.0, 100.0, 999.0, 999.0, 999.0]


def test_read_candles_range_filter(tmp_store_dir: Path) -> None:
    store = ParquetStore(tmp_store_dir)
    candles = [make_candle(utc(2024, 1, 1) + timedelta(hours=i)) for i in range(10)]
    store.write_candles("binance", "BTCUSDT", Interval.H1, candles_to_df(candles))

    read = store.read_candles(
        "binance", "BTCUSDT", Interval.H1, start=utc(2024, 1, 1, 3), end=utc(2024, 1, 1, 7)
    )
    assert read.height == 4
    assert read["open_time"].min() == utc(2024, 1, 1, 3)
    assert read["open_time"].max() == utc(2024, 1, 1, 6)


def test_latest_candle_time(tmp_store_dir: Path) -> None:
    store = ParquetStore(tmp_store_dir)
    assert store.latest_candle_time("binance", "BTCUSDT", Interval.M1) is None

    candles = [make_candle(utc(2024, 1, 1) + timedelta(minutes=i)) for i in range(3)]
    store.write_candles("binance", "BTCUSDT", Interval.M1, candles_to_df(candles))

    assert store.latest_candle_time("binance", "BTCUSDT", Interval.M1) == utc(2024, 1, 1, 0, 2)


def test_write_and_read_funding(tmp_store_dir: Path) -> None:
    store = ParquetStore(tmp_store_dir)
    rates = [make_funding(utc(2024, 1, 1, h * 8)) for h in range(3)]
    store.write_funding("binance", "BTCUSDT", funding_to_df(rates))

    read = store.read_funding("binance", "BTCUSDT")
    assert read.height == 3
    assert store.latest_funding_time("binance", "BTCUSDT") == utc(2024, 1, 1, 16)
