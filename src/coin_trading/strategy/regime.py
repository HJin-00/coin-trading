from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from coin_trading.strategy.indicators import IndicatorSnapshot


class MarketRegime(StrEnum):
    TREND = "TREND"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


@dataclass(frozen=True, slots=True)
class RegimeAssessment:
    regime: MarketRegime
    atr_fraction: float
    ema_spread_fraction: float
    bollinger_width_fraction: float


def classify_regime(
    indicators: IndicatorSnapshot,
    *,
    high_volatility_atr_fraction: float = 0.035,
    trend_ema_spread_fraction: float = 0.005,
) -> RegimeAssessment:
    if indicators.close <= 0:
        raise ValueError("close must be positive")
    atr_fraction = indicators.atr / indicators.close
    ema_spread = abs(indicators.ema_fast - indicators.ema_slow) / indicators.close
    bollinger_width = (
        indicators.bollinger_upper - indicators.bollinger_lower
    ) / indicators.close
    if atr_fraction >= high_volatility_atr_fraction:
        regime = MarketRegime.HIGH_VOLATILITY
    elif ema_spread >= trend_ema_spread_fraction:
        regime = MarketRegime.TREND
    else:
        regime = MarketRegime.RANGE
    return RegimeAssessment(regime, atr_fraction, ema_spread, bollinger_width)
