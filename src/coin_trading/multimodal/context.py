from __future__ import annotations

from typing import Any

from coin_trading.market_data.models import MarketSnapshot
from coin_trading.strategy.indicators import IndicatorSnapshot
from coin_trading.strategy.regime import RegimeAssessment


def build_numeric_context(
    *,
    symbol: str,
    interval: str,
    indicators: IndicatorSnapshot,
    regime: RegimeAssessment,
    market: MarketSnapshot | None = None,
) -> dict[str, Any]:
    """Build a compact context; raw candles are intentionally excluded."""

    context: dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "data_end_ms": indicators.timestamp_ms,
        "close": round(indicators.close, 8),
        "ema_fast": round(indicators.ema_fast, 8),
        "ema_slow": round(indicators.ema_slow, 8),
        "rsi": round(indicators.rsi, 4),
        "macd": round(indicators.macd, 8),
        "macd_signal": round(indicators.macd_signal, 8),
        "bollinger_upper": round(indicators.bollinger_upper, 8),
        "bollinger_lower": round(indicators.bollinger_lower, 8),
        "atr": round(indicators.atr, 8),
        "volume_ratio": round(indicators.volume_ratio, 4),
        "regime": regime.regime.value,
    }
    if market is not None:
        context["funding_rate"] = (
            None if market.funding_rate is None else str(market.funding_rate)
        )
        context["open_interest"] = (
            None if market.open_interest is None else str(market.open_interest)
        )
    return context
