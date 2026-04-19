"""Runtime configuration.

Secrets live in environment variables or a gitignored `.env`. Never committed,
never logged. Trading keys must be trade-only with IP whitelisting — that's an
operational constraint, not something the code can enforce, but the settings
surface makes the key path explicit.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LBankSettings(BaseSettings):
    """Credentials + endpoints for LBank Contract API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LBANK_",
        extra="ignore",
    )

    api_key: SecretStr | None = Field(default=None)
    secret_key: SecretStr | None = Field(default=None)
    rsa_private_key_path: Path | None = Field(
        default=None,
        description="PKCS8 PEM private key path; only needed for RSA signing.",
    )
    base_url: str = Field(default="https://lbkperp.lbank.com")
    ws_url: str = Field(default="wss://lbkperpws.lbank.com/ws")
    product_group: str = Field(
        default="SwapU", description="SwapU = USDT-margined perps, SwapB = coin-margined."
    )

    def reveal_keys(self) -> tuple[str | None, str | None]:
        """Unwrap secrets for client construction. Callers must not log the result."""
        return (
            self.api_key.get_secret_value() if self.api_key else None,
            self.secret_key.get_secret_value() if self.secret_key else None,
        )


class BinanceSettings(BaseSettings):
    """Binance is read-only here (historical data); no keys required for /fapi/v1/klines."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BINANCE_",
        extra="ignore",
    )

    base_url: str = Field(default="https://fapi.binance.com")


class Settings(BaseSettings):
    """Top-level settings namespace."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("data"))

    @property
    def lbank(self) -> LBankSettings:
        return LBankSettings()

    @property
    def binance(self) -> BinanceSettings:
        return BinanceSettings()


settings = Settings()
