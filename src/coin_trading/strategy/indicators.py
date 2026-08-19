from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from coin_trading.market_data.models import Candle


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    timestamp_ms: int
    close: float
    ema_fast: float
    ema_slow: float
    rsi: float
    macd: float
    macd_signal: float
    bollinger_middle: float
    bollinger_upper: float
    bollinger_lower: float
    atr: float
    volume_average: float
    volume_ratio: float


def _ema(values: list[float], period: int) -> list[float]:
    if period <= 0 or len(values) < period:
        raise ValueError(f"at least {period} values are required for EMA")
    seed = sum(values[:period]) / period
    output = [seed]
    multiplier = 2 / (period + 1)
    for value in values[period:]:
        output.append((value - output[-1]) * multiplier + output[-1])
    return output


def _rsi(values: list[float], period: int) -> float:
    if len(values) <= period:
        raise ValueError(f"at least {period + 1} values are required for RSI")
    changes = [
        current - previous for previous, current in zip(values, values[1:], strict=False)
    ]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = ((period - 1) * average_gain + gain) / period
        average_loss = ((period - 1) * average_loss + loss) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    return 100 - (100 / (1 + average_gain / average_loss))


def _atr(candles: list[Candle], period: int) -> float:
    if len(candles) <= period:
        raise ValueError(f"at least {period + 1} candles are required for ATR")
    true_ranges: list[float] = []
    for previous, current in zip(candles, candles[1:], strict=False):
        high = float(current.high)
        low = float(current.low)
        previous_close = float(previous.close)
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    value = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        value = ((period - 1) * value + true_range) / period
    return value


def calculate_indicators(
    candles: list[Candle],
    *,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
    rsi_period: int = 14,
    macd_fast_period: int = 12,
    macd_slow_period: int = 26,
    macd_signal_period: int = 9,
    bollinger_period: int = 20,
    atr_period: int = 14,
    volume_period: int = 20,
) -> IndicatorSnapshot:
    periods = (
        ema_fast_period,
        ema_slow_period,
        rsi_period + 1,
        macd_slow_period + macd_signal_period - 1,
        bollinger_period,
        atr_period + 1,
        volume_period,
    )
    minimum = max(periods)
    if len(candles) < minimum:
        raise ValueError(f"at least {minimum} candles are required")
    if any(not candle.confirmed for candle in candles):
        raise ValueError("indicators require confirmed candles only")

    closes = [float(candle.close) for candle in candles]
    volumes = [float(candle.volume) for candle in candles]
    fast_ema = _ema(closes, ema_fast_period)
    slow_ema = _ema(closes, ema_slow_period)
    macd_fast = _ema(closes, macd_fast_period)
    macd_slow = _ema(closes, macd_slow_period)
    offset = macd_slow_period - macd_fast_period
    macd_values = [fast - slow for fast, slow in zip(macd_fast[offset:], macd_slow, strict=True)]
    signal_values = _ema(macd_values, macd_signal_period)
    bollinger_values = closes[-bollinger_period:]
    middle = sum(bollinger_values) / bollinger_period
    deviation = sqrt(
        sum((value - middle) ** 2 for value in bollinger_values) / bollinger_period
    )
    volume_average = sum(volumes[-volume_period:]) / volume_period

    return IndicatorSnapshot(
        timestamp_ms=candles[-1].end_ms,
        close=closes[-1],
        ema_fast=fast_ema[-1],
        ema_slow=slow_ema[-1],
        rsi=_rsi(closes, rsi_period),
        macd=macd_values[-1],
        macd_signal=signal_values[-1],
        bollinger_middle=middle,
        bollinger_upper=middle + 2 * deviation,
        bollinger_lower=middle - 2 * deviation,
        atr=_atr(candles, atr_period),
        volume_average=volume_average,
        volume_ratio=0.0 if volume_average == 0 else volumes[-1] / volume_average,
    )
