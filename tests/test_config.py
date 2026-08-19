from dataclasses import replace
from decimal import Decimal

import pytest

from coin_trading.config import ConfigurationError, Settings


def safe_settings() -> Settings:
    return Settings(
        symbol="BTCUSDT",
        interval_minutes=60,
        risk_per_trade=Decimal("0.01"),
        max_position_fraction=Decimal("0.30"),
        max_leverage=Decimal("3"),
        daily_loss_limit=Decimal("0.03"),
        max_open_positions=3,
        bybit_testnet=True,
        live_trading=False,
        llm_enabled=False,
        llm_model="gpt-5.6-luna",
    )


def test_safe_defaults_are_valid() -> None:
    safe_settings().validate()


def test_risk_per_trade_cannot_exceed_two_percent() -> None:
    settings = replace(safe_settings(), risk_per_trade=Decimal("0.021"))
    with pytest.raises(ConfigurationError, match="RISK_PER_TRADE"):
        settings.validate()


def test_live_trading_is_unavailable_during_bootstrap() -> None:
    settings = replace(safe_settings(), live_trading=True)
    with pytest.raises(ConfigurationError, match="unavailable"):
        settings.validate()

