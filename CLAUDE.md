# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**CryptoHunter** — a research and trading system for crypto perpetual-futures strategies. Goal: build, validate, and deploy risk-managed strategies across major venues (Binance, Bybit, OKX, Hyperliquid, dYdX, Deribit).

Current stack:

- **Python 3.11+**, managed with `uv` (falls back to plain `pip install -e ".[dev]"`).
- **polars + pyarrow** for dataframes & parquet IO.
- **httpx** (async, HTTP/2) for REST.
- **pydantic / pydantic-settings** for config, **typer** for CLI.
- **ruff** (lint + format), **mypy** (strict), **pytest + pytest-httpx** for tests.

Data layer is the first module landed (see Architecture).

## The specialist team (`.claude/agents/`)

Each agent is a focused expert for one dimension of systematic crypto-futures trading. Invoke them via the Task tool when work falls squarely in their domain; invoke several in parallel for independent subtasks.

| Agent | Use when… |
|---|---|
| `quant-strategist` | Designing or critiquing a trading strategy; stating an edge hypothesis |
| `backtest-engineer` | Validating a strategy, building the backtest framework, hunting overfitting/leakage |
| `risk-manager` | Sizing positions, setting leverage, reviewing exposure, vetoing unsafe trades |
| `execution-engineer` | Integrating exchange APIs, choosing order types, minimizing slippage, handling fills |
| `data-engineer` | Ingesting OHLCV / trades / order-book / funding / OI; building storage; reconciling data |
| `ml-researcher` | Feature engineering, model selection, leakage prevention for ML-driven signals |
| `onchain-derivatives-analyst` | Reading exchange flows, OI, funding extremes, liquidation maps, options skew |
| `funding-basis-specialist` | Designing delta-neutral carry, basis, and cross-venue funding-arb trades |
| `technical-analyst` | Chart structure, levels, indicators — formulated as testable hypotheses |
| `portfolio-allocator` | Multi-strategy capital allocation, regime detection, global risk dial |

## Working principles for this codebase

- **Nothing goes live without `backtest-engineer` + `risk-manager` sign-off.** The strategist proposes, the backtester falsifies, the risk manager sizes. Parallel review, not sequential deference.
- **Edge must be stated before code is written.** If a strategy has no one-sentence edge hypothesis, stop and ask `quant-strategist` to produce one.
- **Costs are not optional in backtests.** Any backtest without realistic fees (taker 0.04–0.06%), funding (per 8h cycle), and slippage (order-book-depth based) is a demo, not evidence.
- **UTC everywhere, no local time.** All timestamps, schedules, and logs in UTC. Exchange server time, not local clock, for signing requests.
- **Reduce-only on all close orders.** Execution code must never risk flipping direction on a partial reject.
- **API keys: trade-only, no withdrawal, IP-whitelisted.** Never commit `.env`. Never log secrets.
- **Data reconciled before it is trusted.** Exchange REST candles vs websocket-constructed candles must match; flag gaps explicitly.

## Architecture

```
src/cryptohunter/
├── schemas.py      Canonical dataclasses + polars schemas (Candle, FundingRate, Interval)
├── storage.py      ParquetStore — partitioned by exchange/symbol/interval/date
├── binance.py      Binance USD-M Futures REST client (async, retry + rate-limit aware)
├── backfill.py     Chunked, resumable, idempotent historical backfill
├── quality.py      Gap / duplicate / monotonicity audits
└── cli.py          Typer CLI (`cryptohunter` entry point)
```

**Key invariants (enforced in code, not docs):**

- Every timestamp is timezone-aware UTC. `Candle` and `FundingRate` reject naive timestamps in `__post_init__`.
- Bar-close convention: `open_time` = bar start, bar covers `[open_time, open_time + interval)`, `close_time` is the last millisecond.
- Backfills are idempotent — writes dedupe on the timestamp key, so rerunning a range is a no-op.
- Parquet partitions are daily to keep files small and enable pushdown via `pl.scan_parquet`.
- `ParquetStore.write_candles` returns **rows written in this call**, not cumulative file size.

## Commands

```bash
# one-time setup
uv venv --python 3.11
uv pip install -e ".[dev]"

# dev loop
.venv/bin/ruff check src tests              # lint
.venv/bin/ruff format src tests             # format
.venv/bin/mypy src                          # types (strict)
.venv/bin/pytest -q                         # tests
.venv/bin/pytest tests/test_storage.py::test_write_and_read_candles   # single test

# CLI (reaches real Binance; use a throwaway range while testing)
.venv/bin/cryptohunter backfill-candles --symbol BTCUSDT --interval 1h \
    --start 2024-01-01 --end 2024-02-01
.venv/bin/cryptohunter backfill-funding  --symbol BTCUSDT \
    --start 2024-01-01 --end 2024-02-01
.venv/bin/cryptohunter audit --symbol BTCUSDT --interval 1h
```

Everything under `data/` is gitignored — parquet partitions live there.

## Branch

All work lives on `claude/init-project-setup-ku64P` until merged.

## Pending (update as the stack materializes)

- WebSocket ingestion (live candles/trades/book) layered on top of the REST backfiller
- Additional venues (Bybit, OKX, Hyperliquid) — generalize `binance.py` into `exchanges/` only when a second client lands, not before
- Backtesting framework (lean toward custom polars-based vectorized; evaluate `nautilus-trader` for event-driven)
- Reconciliation job: REST-candles vs stored-candles daily diff with alerting
- CI (GitHub Actions running the gates above on PRs)
