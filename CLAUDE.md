# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**CryptoHunter** — a research and trading system for crypto perpetual-futures strategies. Goal: build, validate, and deploy risk-managed strategies across major venues (Binance, Bybit, OKX, Hyperliquid, dYdX, Deribit).

The repository is in **initialization phase** — no source code, tests, or build system exist yet. The first concrete artifacts are the specialist agent definitions under `.claude/agents/`. Update this file as real code, tooling, and commands come online.

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

## Branch

All work lives on `claude/init-project-setup-ku64P` until merged.

## Pending (update this section as the stack materializes)

- Language / runtime choice (Python + polars/pandas + asyncio is the default starting point)
- Backtesting framework (custom vs. `vectorbt` / `nautilus-trader` / `backtrader`)
- Exchange-client library (`ccxt` for breadth; native clients for latency-sensitive paths)
- Storage (parquet for cold, TimescaleDB/ClickHouse for warm)
- CI, lint, test commands — none yet
