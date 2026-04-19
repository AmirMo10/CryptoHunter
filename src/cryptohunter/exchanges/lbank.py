"""LBank USDT-M perpetual-futures REST client.

Docs PDF ("Introduction - LBank CONTRACT API"):
  REST base:       https://lbkperp.lbank.com/
  Public prefix:   /cfd/openApi/v1/pub
  Private prefix:  /cfd/openApi/v1/prv

Signing scheme (verified byte-for-byte against the PDF's documented example
in tests/test_lbank_signer.py):

  1. Build `parameters` from the request payload MINUS `sign`, PLUS the three
     header params (`signature_method`, `timestamp`, `echostr`). Sort by key
     alphabetically, join as `k=v&k=v&...`.
  2. preparedStr = md5(parameters).hex().upper()
  3. sign = HmacSHA256(preparedStr, secret).hex()      (or RSA-SHA256 base64)

Private endpoints are stubbed with NotImplementedError — the public contract
docs do not publish trading/account endpoint schemas. The signer and transport
are wired so private endpoints slot in trivially once a schema is known.

Rate-limit awareness: LBank publishes error_code=10012 ("request too frequent")
and 183 ("exceeded max query count per second") — both mapped to retries with
exponential backoff. 178 ("API key limit exceeded") is a hard stop (no retry).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import string
import time
from types import TracebackType
from typing import Any, Final, Self

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://lbkperp.lbank.com"
PUB_PREFIX = "/cfd/openApi/v1/pub"
PRV_PREFIX = "/cfd/openApi/v1/prv"

SIGMETHOD_HMAC: Final[str] = "HmacSHA256"
SIGMETHOD_RSA: Final[str] = "RSA"

ECHOSTR_MIN: Final[int] = 30
ECHOSTR_MAX: Final[int] = 40

# Error codes that should be retried vs. surfaced.
_RETRYABLE_ERROR_CODES: Final[frozenset[str]] = frozenset({"10012", "183", "10004"})
# Error codes that are hard stops even with correct signing.
_FATAL_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"178", "176", "177", "179", "180", "10008", "10009"}
)


class LBankError(RuntimeError):
    """Non-zero business error returned in the response envelope."""

    def __init__(self, code: str, msg: str, endpoint: str) -> None:
        super().__init__(f"lbank {endpoint} error_code={code} msg={msg!r}")
        self.code = code
        self.msg = msg
        self.endpoint = endpoint


class LBankHTTPError(RuntimeError):
    """Transport-level failure (non-200 after retries, malformed body, etc)."""


class LBankSigner:
    """Stateless signer for LBank Contract API.

    Deliberately separate from the HTTP client so it can be unit-tested against
    the documented fixture without any network setup.
    """

    def __init__(self, api_key: str, secret_key: str, signature_method: str = SIGMETHOD_HMAC):
        if signature_method not in {SIGMETHOD_HMAC, SIGMETHOD_RSA}:
            raise ValueError(f"unsupported signature_method: {signature_method}")
        if signature_method == SIGMETHOD_RSA:
            raise NotImplementedError(
                "RSA signing is not implemented yet (PDF describes the scheme but "
                "we have no RSA test fixture to verify against). Use HmacSHA256."
            )
        self.api_key = api_key
        self._secret = secret_key
        self.signature_method = signature_method

    @staticmethod
    def build_parameters(params: dict[str, Any]) -> str:
        """Canonical `k=v&k=v&...` string: drop `sign`, sort keys alphabetically.

        Values are stringified as-is (no URL encoding at the signing stage —
        the PDF example feeds the raw form into MD5).
        """
        items = sorted((k, v) for k, v in params.items() if k != "sign")
        return "&".join(f"{k}={v}" for k, v in items)

    @staticmethod
    def prepared_str(parameters: str) -> str:
        return hashlib.md5(parameters.encode("utf-8")).hexdigest().upper()

    def sign(self, params: dict[str, Any]) -> str:
        prepared = self.prepared_str(self.build_parameters(params))
        return hmac.new(
            self._secret.encode("utf-8"),
            prepared.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def generate_echostr(length: int = 36) -> str:
    """Random alphanumeric of length in [30, 40] as required by the header spec."""
    if not ECHOSTR_MIN <= length <= ECHOSTR_MAX:
        raise ValueError(f"echostr length must be in [{ECHOSTR_MIN}, {ECHOSTR_MAX}]")
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def current_timestamp_ms() -> int:
    return int(time.time() * 1000)


class LBankContract:
    """Async client for LBank Contract API (USDT-margined perps).

    Only the 4 public endpoints documented in the PDF are implemented; private
    endpoints raise NotImplementedError with a pointer at the doc gap. The
    signing and request pipelines are complete, so adding a private endpoint
    means a one-line method once its schema is known.
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
        request_pause_s: float = 0.1,
        max_retries: int = 5,
        product_group: str = "SwapU",
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
        self._product_group = product_group
        self._signer: LBankSigner | None = (
            LBankSigner(api_key, secret_key) if api_key and secret_key else None
        )

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

    async def _public_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params or {}, private=False)

    async def _private(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._signer is None:
            raise LBankHTTPError("private endpoint requires api_key and secret_key")
        return await self._request(method, path, params=params or {}, private=True)

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any], private: bool
    ) -> Any:
        attempt = 0
        while True:
            attempt += 1

            headers = {"Content-Type": "application/json"}
            query: dict[str, Any] | None
            body: dict[str, Any] | None

            if private:
                assert self._signer is not None
                full_params = dict(params)
                ts = str(current_timestamp_ms())
                echostr = generate_echostr()
                full_params.update(
                    {
                        "api_key": self._signer.api_key,
                        "signature_method": self._signer.signature_method,
                        "timestamp": ts,
                        "echostr": echostr,
                    }
                )
                sign = self._signer.sign(full_params)
                full_params["sign"] = sign
                headers.update(
                    {
                        "timestamp": ts,
                        "signature_method": self._signer.signature_method,
                        "echostr": echostr,
                    }
                )
                if method.upper() == "GET":
                    query, body = full_params, None
                else:
                    query, body = None, full_params
            else:
                query, body = (params or None), None

            try:
                r = await self._client.request(
                    method,
                    path,
                    params=query,
                    json=body,
                    headers=headers,
                )
            except httpx.HTTPError as e:
                if attempt >= self._max_retries:
                    raise LBankHTTPError(f"network error after {attempt} attempts: {e}") from e
                await asyncio.sleep(min(2**attempt, 30))
                continue

            if r.status_code in {429, 418}:
                retry_after = float(r.headers.get("Retry-After", "1"))
                log.warning(
                    "lbank rate-limited (status=%s) - sleeping %ss", r.status_code, retry_after
                )
                await asyncio.sleep(retry_after)
                continue
            if 500 <= r.status_code < 600:
                if attempt >= self._max_retries:
                    raise LBankHTTPError(f"server error {r.status_code} after {attempt} attempts")
                await asyncio.sleep(min(2**attempt, 30))
                continue
            if r.status_code != 200:
                raise LBankHTTPError(f"HTTP {r.status_code}: {r.text[:200]}")

            try:
                payload = r.json()
            except ValueError as e:
                raise LBankHTTPError(f"non-JSON response: {r.text[:200]}") from e

            if not isinstance(payload, dict):
                raise LBankHTTPError(f"unexpected response shape: {payload!r}")

            result = payload.get("result", True)
            # LBank returns result as either bool or the string "true"/"false".
            if isinstance(result, str):
                result = result.lower() == "true"
            error_code = str(payload.get("error_code", "0"))

            if result and error_code in {"0", "None", ""}:
                await asyncio.sleep(self._request_pause_s)
                return payload.get("data")

            if error_code in _FATAL_ERROR_CODES:
                raise LBankError(error_code, str(payload.get("msg", "")), endpoint=path)
            if error_code in _RETRYABLE_ERROR_CODES and attempt < self._max_retries:
                await asyncio.sleep(min(2**attempt, 30))
                continue
            raise LBankError(error_code, str(payload.get("msg", "")), endpoint=path)

    # ------------------------------------------------------------------
    # Public endpoints (documented in the PDF).
    # ------------------------------------------------------------------

    async def get_time(self) -> int:
        """Server time in milliseconds. Use this to set `timestamp` on signed calls."""
        data = await self._public_get(f"{PUB_PREFIX}/getTime")
        # Data shape per the PDF is a raw integer or {"timestamp": int}; handle both.
        if isinstance(data, int):
            return data
        if isinstance(data, dict) and "timestamp" in data:
            return int(data["timestamp"])
        raise LBankHTTPError(f"unexpected getTime payload: {data!r}")

    async def instruments(self, product_group: str | None = None) -> list[dict[str, Any]]:
        """Contract instrument list (tick size, lot size, status, etc.)."""
        data = await self._public_get(
            f"{PUB_PREFIX}/instrument",
            {"productGroup": product_group or self._product_group},
        )
        if isinstance(data, list):
            return data
        raise LBankHTTPError(f"unexpected instrument payload: {data!r}")

    async def market_data(self, product_group: str | None = None) -> list[dict[str, Any]]:
        """Current market snapshot (last price, volumes, funding-rate snapshot).

        The `prePositionFeeRate` field on each entry is the CURRENT funding rate;
        LBank does not expose historical funding, so capturing this periodically
        is the only way to build a funding time-series for LBank.
        """
        data = await self._public_get(
            f"{PUB_PREFIX}/marketData",
            {"productGroup": product_group or self._product_group},
        )
        if isinstance(data, list):
            return data
        raise LBankHTTPError(f"unexpected marketData payload: {data!r}")

    async def market_order(self, symbol: str, depth: int = 10) -> dict[str, Any]:
        """Orderbook snapshot ("handicap") for `symbol` at `depth` levels per side."""
        data = await self._public_get(
            f"{PUB_PREFIX}/marketOrder",
            {"symbol": symbol, "depth": depth},
        )
        if isinstance(data, dict):
            return data
        raise LBankHTTPError(f"unexpected marketOrder payload: {data!r}")

    # ------------------------------------------------------------------
    # Private endpoints — schemas not published in the public doc PDF.
    # Keep these stubs so callers get a clear error, not a mysterious 404.
    # ------------------------------------------------------------------

    async def account(self, asset: str = "USDT") -> dict[str, Any]:
        raise NotImplementedError(
            "prv/account schema is not published in the public docs PDF. "
            "Use documented test credentials to probe the live endpoint, then wire it here."
        )

    async def place_order(self, **_: Any) -> dict[str, Any]:
        raise NotImplementedError(
            "prv order placement not implemented — private schema pending. "
            "Execution code must go through risk-manager review before this lands."
        )

    async def cancel_order(self, **_: Any) -> dict[str, Any]:
        raise NotImplementedError("prv order cancel not implemented — private schema pending.")

    async def positions(self, **_: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("prv positions not implemented — private schema pending.")
