from __future__ import annotations

from collections.abc import Sequence

from coin_trading.market_data.models import Candle


class DataValidationError(ValueError):
    """Raised when market data is unsafe to use for research or trading."""


def validate_candles(
    candles: Sequence[Candle],
    *,
    expected_interval_ms: int,
    require_contiguous: bool = True,
    require_confirmed: bool = True,
) -> None:
    if expected_interval_ms <= 0:
        raise ValueError("expected_interval_ms must be positive")
    if not candles:
        raise DataValidationError("candle collection is empty")

    first = candles[0]
    seen: set[int] = set()
    previous_start: int | None = None
    for candle in candles:
        if candle.symbol != first.symbol or candle.interval != first.interval:
            raise DataValidationError("mixed symbol or interval in candle collection")
        if candle.start_ms in seen:
            raise DataValidationError(f"duplicate candle at {candle.start_ms}")
        seen.add(candle.start_ms)
        if previous_start is not None:
            distance = candle.start_ms - previous_start
            if distance <= 0:
                raise DataValidationError("candles are not in strictly ascending order")
            if require_contiguous and distance != expected_interval_ms:
                raise DataValidationError(
                    f"missing candle between {previous_start} and {candle.start_ms}"
                )
        previous_start = candle.start_ms

        if candle.end_ms != candle.start_ms + expected_interval_ms - 1:
            raise DataValidationError(f"invalid candle duration at {candle.start_ms}")
        if require_confirmed and not candle.confirmed:
            raise DataValidationError(f"unconfirmed candle at {candle.start_ms}")
        if min(candle.open, candle.high, candle.low, candle.close) <= 0:
            raise DataValidationError(f"non-positive price at {candle.start_ms}")
        if candle.high < max(candle.open, candle.close) or candle.low > min(
            candle.open, candle.close
        ):
            raise DataValidationError(f"inconsistent OHLC at {candle.start_ms}")
        if candle.high < candle.low:
            raise DataValidationError(f"high below low at {candle.start_ms}")
        if candle.volume < 0 or candle.turnover < 0:
            raise DataValidationError(f"negative volume or turnover at {candle.start_ms}")
