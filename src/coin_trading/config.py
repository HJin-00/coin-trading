from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class ConfigurationError(ValueError):
    """Raised when safety-critical configuration is invalid."""


def _decimal(name: str, default: str) -> Decimal:
    try:
        return Decimal(os.getenv(name, default))
    except InvalidOperation as exc:
        raise ConfigurationError(f"{name} must be a decimal number") from exc


def _boolean(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise ConfigurationError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class Settings:
    symbol: str
    interval_minutes: int
    risk_per_trade: Decimal
    max_position_fraction: Decimal
    max_leverage: Decimal
    daily_loss_limit: Decimal
    max_open_positions: int
    bybit_testnet: bool
    live_trading: bool
    llm_enabled: bool
    llm_model: str

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            symbol=os.getenv("TRADING_SYMBOL", "BTCUSDT").upper(),
            interval_minutes=int(os.getenv("TRADING_INTERVAL", "60")),
            risk_per_trade=_decimal("RISK_PER_TRADE", "0.01"),
            max_position_fraction=_decimal("MAX_POSITION_FRACTION", "0.30"),
            max_leverage=_decimal("MAX_LEVERAGE", "3"),
            daily_loss_limit=_decimal("DAILY_LOSS_LIMIT", "0.03"),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
            bybit_testnet=_boolean("BYBIT_TESTNET", "true"),
            live_trading=_boolean("LIVE_TRADING", "false"),
            llm_enabled=_boolean("LLM_ENABLED", "false"),
            llm_model=os.getenv("LLM_MODEL", "gpt-5.6-luna"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.symbol.endswith("USDT"):
            raise ConfigurationError("only USDT-settled symbols are allowed initially")
        if self.interval_minutes <= 0:
            raise ConfigurationError("TRADING_INTERVAL must be positive")
        if not Decimal("0") < self.risk_per_trade <= Decimal("0.02"):
            raise ConfigurationError("RISK_PER_TRADE must be in (0, 0.02]")
        if not Decimal("0") < self.max_position_fraction <= Decimal("0.50"):
            raise ConfigurationError("MAX_POSITION_FRACTION must be in (0, 0.50]")
        if not Decimal("0") < self.max_leverage <= Decimal("3"):
            raise ConfigurationError("MAX_LEVERAGE must be in (0, 3]")
        if not Decimal("0") < self.daily_loss_limit <= Decimal("0.05"):
            raise ConfigurationError("DAILY_LOSS_LIMIT must be in (0, 0.05]")
        if not 1 <= self.max_open_positions <= 5:
            raise ConfigurationError("MAX_OPEN_POSITIONS must be between 1 and 5")
        if self.live_trading:
            raise ConfigurationError("live trading is intentionally unavailable in this phase")

