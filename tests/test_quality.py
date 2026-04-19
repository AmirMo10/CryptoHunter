from __future__ import annotations

from datetime import timedelta

from cryptohunter.quality import audit_candles, find_candle_gaps, find_duplicate_timestamps
from cryptohunter.schemas import Interval, candles_to_df

from .conftest import make_candle, utc


def _continuous(n: int) -> list:
    return [make_candle(utc(2024, 1, 1) + timedelta(minutes=i)) for i in range(n)]


def test_no_gaps_in_continuous_series() -> None:
    df = candles_to_df(_continuous(10))
    assert find_candle_gaps(df, Interval.M1) == []


def test_detects_single_gap() -> None:
    candles = [
        make_candle(utc(2024, 1, 1, 0, 0)),
        make_candle(utc(2024, 1, 1, 0, 1)),
        make_candle(utc(2024, 1, 1, 0, 5)),
    ]
    gaps = find_candle_gaps(candles_to_df(candles), Interval.M1)
    assert len(gaps) == 1
    assert gaps[0].missing_bars == 3
    assert gaps[0].start == utc(2024, 1, 1, 0, 2)
    assert gaps[0].end == utc(2024, 1, 1, 0, 5)


def test_duplicates_detection() -> None:
    candles = _continuous(3) + [make_candle(utc(2024, 1, 1))]
    df = candles_to_df(candles)
    assert find_duplicate_timestamps(df, "open_time") == 1


def test_audit_candles_clean() -> None:
    report = audit_candles(candles_to_df(_continuous(60)), Interval.M1)
    assert report.ok
    assert report.rows == 60
    assert report.first_ts == utc(2024, 1, 1)
    assert report.last_ts == utc(2024, 1, 1, 0, 59)


def test_audit_candles_with_issues() -> None:
    candles = [
        make_candle(utc(2024, 1, 1, 0, 0)),
        make_candle(utc(2024, 1, 1, 0, 1)),
        make_candle(utc(2024, 1, 1, 0, 3)),
    ]
    report = audit_candles(candles_to_df(candles), Interval.M1)
    assert not report.ok
    assert len(report.gaps) == 1
    assert report.gaps[0].missing_bars == 1


def test_audit_empty() -> None:
    df = candles_to_df([])
    report = audit_candles(df, Interval.M1)
    assert report.ok
    assert report.rows == 0
