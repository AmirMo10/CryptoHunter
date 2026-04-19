"""Exchange clients.

Each venue gets its own module. `binance` is the historical-data source;
`lbank` is the live-execution venue. The clients intentionally do NOT share
a base class — their REST conventions, signing schemes, and response shapes
differ enough that premature abstraction is a worse bet than two clear
implementations. When a third venue lands, factor out the shared pieces.
"""

from __future__ import annotations

from .binance import BinanceFutures, BinanceFuturesError
from .lbank import LBankContract, LBankError, LBankHTTPError

__all__ = [
    "BinanceFutures",
    "BinanceFuturesError",
    "LBankContract",
    "LBankError",
    "LBankHTTPError",
]
