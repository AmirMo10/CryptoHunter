"""Command-line interface."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from dateutil import parser as dtparser

from .backfill import backfill_candles, backfill_funding
from .binance import BinanceFutures
from .quality import audit_candles
from .schemas import Interval
from .storage import ParquetStore

app = typer.Typer(help="CryptoHunter — crypto futures data & research CLI.", no_args_is_help=True)


def _parse_utc(s: str) -> datetime:
    dt = dtparser.parse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


DataDir = Annotated[Path, typer.Option("--data-dir", help="Parquet root directory.")]
Verbose = Annotated[bool, typer.Option("--verbose", "-v")]


@app.command("backfill-candles")
def backfill_candles_cmd(
    symbol: Annotated[str, typer.Option(help="e.g. BTCUSDT")],
    interval: Annotated[Interval, typer.Option(help="1m, 5m, 15m, 1h, 4h, 1d, etc.")],
    start: Annotated[str, typer.Option(help="UTC ISO timestamp or date, inclusive.")],
    end: Annotated[str, typer.Option(help="UTC ISO timestamp or date, exclusive.")],
    data_dir: DataDir = Path("data"),
    no_resume: Annotated[bool, typer.Option("--no-resume")] = False,
    verbose: Verbose = False,
) -> None:
    """Backfill historical candles from Binance USD-M Futures."""
    _setup_logging(verbose)

    async def _run() -> None:
        store = ParquetStore(data_dir)
        async with BinanceFutures() as client:
            result = await backfill_candles(
                client,
                store,
                symbol=symbol,
                interval=interval,
                start=_parse_utc(start),
                end=_parse_utc(end),
                resume=not no_resume,
            )
        typer.echo(
            f"{result.symbol} {interval.value}: wrote/updated {result.rows_written} rows "
            f"covering [{result.start}, {result.end})"
        )

    asyncio.run(_run())


@app.command("backfill-funding")
def backfill_funding_cmd(
    symbol: Annotated[str, typer.Option(help="e.g. BTCUSDT")],
    start: Annotated[str, typer.Option()],
    end: Annotated[str, typer.Option()],
    data_dir: DataDir = Path("data"),
    no_resume: Annotated[bool, typer.Option("--no-resume")] = False,
    verbose: Verbose = False,
) -> None:
    """Backfill historical funding rates from Binance USD-M Futures."""
    _setup_logging(verbose)

    async def _run() -> None:
        store = ParquetStore(data_dir)
        async with BinanceFutures() as client:
            result = await backfill_funding(
                client,
                store,
                symbol=symbol,
                start=_parse_utc(start),
                end=_parse_utc(end),
                resume=not no_resume,
            )
        typer.echo(
            f"{result.symbol} funding: wrote/updated {result.rows_written} rows "
            f"covering [{result.start}, {result.end})"
        )

    asyncio.run(_run())


@app.command("audit")
def audit_cmd(
    symbol: Annotated[str, typer.Option()],
    interval: Annotated[Interval, typer.Option()],
    data_dir: DataDir = Path("data"),
    exchange: Annotated[str, typer.Option()] = "binance",
) -> None:
    """Audit stored candles for gaps, duplicates, and monotonicity."""
    store = ParquetStore(data_dir)
    df = store.read_candles(exchange, symbol, interval)
    report = audit_candles(df, interval)
    typer.echo(report.summary())
    if not report.ok:
        for gap in report.gaps[:20]:
            typer.echo(f"  gap: {gap.start} → {gap.end} ({gap.missing_bars} bars)")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
