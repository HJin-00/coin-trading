from __future__ import annotations

from decimal import Decimal

from coin_trading.market_data.models import Candle


def resample_candles(candles: list[Candle], *, multiple: int, interval: str) -> list[Candle]:
    """Aggregate complete, aligned groups without manufacturing partial candles."""
    if multiple <= 1:
        raise ValueError("multiple must be greater than one")
    if not candles:
        return []
    base_duration = candles[0].end_ms - candles[0].start_ms + 1
    target_duration = base_duration * multiple
    first_aligned = next(
        (index for index, candle in enumerate(candles) if candle.start_ms % target_duration == 0),
        len(candles),
    )
    aligned = candles[first_aligned:]
    output: list[Candle] = []
    for offset in range(0, len(aligned), multiple):
        group = aligned[offset : offset + multiple]
        if len(group) != multiple:
            break
        if any(not candle.confirmed for candle in group):
            raise ValueError("resampling requires confirmed candles")
        if any(
            current.start_ms - previous.start_ms != base_duration
            for previous, current in zip(group, group[1:], strict=False)
        ):
            raise ValueError("cannot resample candles with gaps")
        if group[-1].end_ms - group[0].start_ms + 1 != target_duration:
            raise ValueError("resampled candle is not aligned to its target duration")
        output.append(
            Candle(
                symbol=group[0].symbol,
                interval=interval,
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                open=group[0].open,
                high=max(candle.high for candle in group),
                low=min(candle.low for candle in group),
                close=group[-1].close,
                volume=sum((candle.volume for candle in group), Decimal("0")),
                turnover=sum((candle.turnover for candle in group), Decimal("0")),
                confirmed=True,
            )
        )
    return output
