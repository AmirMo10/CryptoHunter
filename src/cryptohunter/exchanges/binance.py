"""Binance USD-M Futures REST client (read-only historical data).

Docs: https://binance-docs.github.io/apidocs/futures/en/

Endpoints used:
  GET /fapi/v1/klines        — historical candles, 1500 per request max
  GET /fapi/v1/fundingRate   — historical funding rates, 1000 per request max
  GET /fapi/v1/exchangeInfo  — symbol metadata

Rate limits: 2400 weight/min on IP. Klines cost 2-10 weight depending on limit;
fundingRate costs 1. We stay well under with per-request sleeps and backoff.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import httpx

from ..schemas import Candle, FundingRate, Interval

log = logging.getLogger(__name__)

BASE_URL = "https://fapi.binance.com"
KLINES_LIMIT = 1500
FUNDING_LIMIT = 1000


class BinanceFuturesError(RuntimeError):
    pass


class BinanceFutures:
    def __init__(
        self,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
        request_pause_s: float = 0.1,
        max_retries: int = 5,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            http2=True,
            headers={"User-Agent": "cryptohunter/0.1"},
        )
        self._request_pause_s = request_pause_s
        self._max_retries = max_retries

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                r = await self._client.get(path, params=params)
            except httpx.HTTPError as e:
                if attempt >= self._max_retries:
                    raise BinanceFuturesError(f"network error after {attempt} attempts: {e}") from e
                await asyncio.sleep(min(2**attempt, 30))
                continue

            if r.status_code in {429, 418}:
                retry_after = float(r.headers.get("Retry-After", "1"))
                log.warning(
                    "binance rate-limited (status=%s) - sleeping %ss",
                    r.status_code,
                    retry_after,
                )
                await asyncio.sleep(retry_after)
                continue
            if 500 <= r.status_code < 600:
                if attempt >= self._max_retries:
                    raise BinanceFuturesError(
                        f"server error {r.status_code} after {attempt} attempts"
                    )
                await asyncio.sleep(min(2**attempt, 30))
                continue
            if r.status_code != 200:
                raise BinanceFuturesError(f"HTTP {r.status_code}: {r.text[:200]}")

            await asyncio.sleep(self._request_pause_s)
            return r.json()

    async def klines(
        self,
        symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        limit: int = KLINES_LIMIT,
    ) -> list[Candle]:
        _require_utc(start, "start")
        _require_utc(end, "end")
        if limit > KLINES_LIMIT:
            raise ValueError(f"limit must be <= {KLINES_LIMIT}")

        raw = await self._get(
            "/fapi/v1/klines",
            {
                "symbol": symbol.upper(),
                "interval": interval.value,
                "startTime": _ms(start),
                "endTime": _ms(end) - 1,
                "limit": limit,
            },
        )
        return [_parse_kline(row) for row in raw]

    async def funding_rates(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int = FUNDING_LIMIT,
    ) -> list[FundingRate]:
        _require_utc(start, "start")
        _require_utc(end, "end")
        if limit > FUNDING_LIMIT:
            raise ValueError(f"limit must be <= {FUNDING_LIMIT}")

        raw = await self._get(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol.upper(),
                "startTime": _ms(start),
                "endTime": _ms(end) - 1,
                "limit": limit,
            },
        )
        return [_parse_funding(row) for row in raw]

    async def exchange_info(self) -> dict[str, Any]:
        data = await self._get("/fapi/v1/exchangeInfo", {})
        assert isinstance(data, dict)
        return data


def _require_utc(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() != UTC.utcoffset(dt):
        raise ValueError(f"{name} must be timezone-aware UTC")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _parse_kline(row: list[Any]) -> Candle:
    return Candle(
        open_time=_from_ms(int(row[0])),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time=_from_ms(int(row[6])),
        quote_volume=float(row[7]),
        trade_count=int(row[8]),
        taker_buy_base_volume=float(row[9]),
        taker_buy_quote_volume=float(row[10]),
    )


def _parse_funding(row: dict[str, Any]) -> FundingRate:
    return FundingRate(
        funding_time=_from_ms(int(row["fundingTime"])),
        funding_rate=float(row["fundingRate"]),
        mark_price=float(row.get("markPrice", 0.0) or 0.0),
    )
