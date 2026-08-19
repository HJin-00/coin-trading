from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from coin_trading.domain import Side
from coin_trading.market_data.models import Candle
from coin_trading.strategy.indicators import IndicatorSnapshot, calculate_indicators
from coin_trading.strategy.regime import MarketRegime, RegimeAssessment, classify_regime


@dataclass(frozen=True, slots=True)
class StrategyParameters:
    breakout_lookback: int = 20
    breakout_volume_ratio: float = 1.5
    pullback_atr_distance: float = 0.5
    high_volatility_atr_fraction: float = 0.035
    trend_ema_spread_fraction: float = 0.005


@dataclass(frozen=True, slots=True)
class Signal:
    side: Side
    reason: str
    indicators: IndicatorSnapshot
    regime: RegimeAssessment


class BaselineStrategy:
    """Trend pullback and volume-confirmed breakout baseline."""

    minimum_history = 60

    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        self.parameters = parameters or StrategyParameters()

    def evaluate(self, candles: list[Candle]) -> Signal:
        if len(candles) < max(self.minimum_history, self.parameters.breakout_lookback + 1):
            raise ValueError("insufficient history for baseline strategy")
        indicators = calculate_indicators(candles)
        regime = classify_regime(
            indicators,
            high_volatility_atr_fraction=self.parameters.high_volatility_atr_fraction,
            trend_ema_spread_fraction=self.parameters.trend_ema_spread_fraction,
        )
        if regime.regime is MarketRegime.HIGH_VOLATILITY:
            return Signal(Side.NO_TRADE, "high_volatility_guard", indicators, regime)

        previous = candles[-(self.parameters.breakout_lookback + 1) : -1]
        previous_high = max(float(candle.high) for candle in previous)
        previous_low = min(float(candle.low) for candle in previous)
        bullish = indicators.ema_fast > indicators.ema_slow
        bearish = indicators.ema_fast < indicators.ema_slow
        volume_confirmed = indicators.volume_ratio >= self.parameters.breakout_volume_ratio

        if indicators.close > previous_high and volume_confirmed and bullish:
            return Signal(Side.LONG, "bullish_volume_breakout", indicators, regime)
        if indicators.close < previous_low and volume_confirmed and bearish:
            return Signal(Side.SHORT, "bearish_volume_breakout", indicators, regime)

        pullback_distance = abs(indicators.close - indicators.ema_fast)
        near_fast_ema = pullback_distance <= indicators.atr * self.parameters.pullback_atr_distance
        if regime.regime is MarketRegime.TREND and near_fast_ema:
            if bullish and 40 <= indicators.rsi <= 65 and indicators.macd >= indicators.macd_signal:
                return Signal(Side.LONG, "bullish_trend_pullback", indicators, regime)
            if bearish and 35 <= indicators.rsi <= 60 and indicators.macd <= indicators.macd_signal:
                return Signal(Side.SHORT, "bearish_trend_pullback", indicators, regime)
        return Signal(Side.NO_TRADE, "conditions_not_met", indicators, regime)

    def evaluate_timeframes(
        self,
        timeframes: Mapping[str, list[Candle]],
        *,
        primary: str,
    ) -> Signal:
        if primary not in timeframes:
            raise ValueError("primary timeframe is missing")
        if len(timeframes) < 2:
            raise ValueError("at least two timeframes are required")
        signal = self.evaluate(timeframes[primary])
        if signal.side is Side.NO_TRADE:
            return signal

        for name, candles in timeframes.items():
            if name == primary:
                continue
            indicators = calculate_indicators(candles)
            regime = classify_regime(
                indicators,
                high_volatility_atr_fraction=self.parameters.high_volatility_atr_fraction,
                trend_ema_spread_fraction=self.parameters.trend_ema_spread_fraction,
            )
            aligned = (signal.side is Side.LONG and indicators.ema_fast > indicators.ema_slow) or (
                signal.side is Side.SHORT and indicators.ema_fast < indicators.ema_slow
            )
            if regime.regime is not MarketRegime.TREND or not aligned:
                return Signal(
                    Side.NO_TRADE,
                    f"timeframe_confirmation_failed:{name}",
                    signal.indicators,
                    signal.regime,
                )
        return signal
