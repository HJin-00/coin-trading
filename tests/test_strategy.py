from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from coin_trading.domain import Side
from coin_trading.market_data import Candle
from coin_trading.strategy import (
    BacktestConfig,
    Backtester,
    BaselineStrategy,
    IndicatorSnapshot,
    MarketRegime,
    RegimeAssessment,
    Signal,
    StrategyParameters,
    calculate_indicators,
    resample_candles,
    walk_forward,
)


def make_candles(count: int, *, step: Decimal = Decimal("0.2")) -> list[Candle]:
    candles: list[Candle] = []
    price = Decimal("100")
    for index in range(count):
        close = price + step
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval="1",
                start_ms=index * 60_000,
                end_ms=(index + 1) * 60_000 - 1,
                open=price,
                high=max(price, close) + Decimal("1"),
                low=min(price, close) - Decimal("1"),
                close=close,
                volume=Decimal("10"),
                turnover=Decimal("1000"),
                confirmed=True,
            )
        )
        price = close
    return candles


def test_indicators_are_calculated_from_confirmed_history() -> None:
    candles = make_candles(70)
    snapshot = calculate_indicators(candles)
    assert snapshot.ema_fast > snapshot.ema_slow
    assert snapshot.atr > 0
    assert snapshot.volume_ratio == pytest.approx(1.0)

    candles[-1] = replace(candles[-1], confirmed=False)
    with pytest.raises(ValueError, match="confirmed"):
        calculate_indicators(candles)


def test_resample_uses_only_complete_groups() -> None:
    candles = make_candles(5)
    output = resample_candles(candles, multiple=2, interval="2")
    assert len(output) == 2
    assert output[0].open == candles[0].open
    assert output[0].close == candles[1].close
    assert output[0].volume == Decimal("20")


def test_resample_discards_leading_unaligned_candle() -> None:
    candles = make_candles(5)[1:]
    output = resample_candles(candles, multiple=2, interval="2")
    assert output[0].start_ms == 120_000


def test_baseline_detects_volume_confirmed_breakout() -> None:
    candles = make_candles(60, step=Decimal("0.05"))
    previous = candles[-1]
    candles[-1] = Candle(
        symbol=previous.symbol,
        interval=previous.interval,
        start_ms=previous.start_ms,
        end_ms=previous.end_ms,
        open=previous.open,
        high=Decimal("115"),
        low=previous.low,
        close=Decimal("114"),
        volume=Decimal("100"),
        turnover=Decimal("11000"),
        confirmed=True,
    )
    signal = BaselineStrategy().evaluate(candles)
    assert signal.side is Side.LONG
    assert signal.reason == "bullish_volume_breakout"


def test_multitimeframe_gate_requires_aligned_higher_trend() -> None:
    primary = make_candles(60, step=Decimal("0.05"))
    last = primary[-1]
    primary[-1] = replace(
        last,
        high=Decimal("115"),
        close=Decimal("114"),
        volume=Decimal("100"),
        turnover=Decimal("11000"),
    )
    higher = make_candles(70, step=Decimal("-0.2"))
    signal = BaselineStrategy().evaluate_timeframes(
        {"1h": primary, "4h": higher}, primary="1h"
    )
    assert signal.side is Side.NO_TRADE
    assert signal.reason == "timeframe_confirmation_failed:4h"


def fixed_signal(side: Side, timestamp_ms: int, atr: float = 2.0) -> Signal:
    indicators = IndicatorSnapshot(
        timestamp_ms=timestamp_ms,
        close=100,
        ema_fast=101,
        ema_slow=99,
        rsi=50,
        macd=1,
        macd_signal=0.5,
        bollinger_middle=100,
        bollinger_upper=105,
        bollinger_lower=95,
        atr=atr,
        volume_average=10,
        volume_ratio=1,
    )
    regime = RegimeAssessment(MarketRegime.TREND, 0.02, 0.02, 0.1)
    return Signal(side, "test", indicators, regime)


class OneLongSignal:
    minimum_history = 2

    def evaluate(self, candles: list[Candle]) -> Signal:
        side = Side.LONG if candles[-1].start_ms == 60_000 else Side.NO_TRADE
        return fixed_signal(side, candles[-1].end_ms)


def test_backtest_enters_on_next_bar_and_uses_conservative_stop_first() -> None:
    candles = make_candles(4, step=Decimal("0"))
    third = candles[2]
    candles[2] = Candle(
        third.symbol,
        third.interval,
        third.start_ms,
        third.end_ms,
        Decimal("100"),
        Decimal("109"),
        Decimal("95"),
        Decimal("101"),
        third.volume,
        third.turnover,
        True,
    )
    config = BacktestConfig(fee_rate=Decimal("0"), slippage_bps=Decimal("0"))
    result = Backtester(OneLongSignal(), config).run(candles)
    assert len(result.trades) == 1
    assert result.trades[0].entry_time_ms == candles[2].start_ms
    assert result.trades[0].exit_reason == "stop"
    assert result.trades[0].net_pnl < 0


def test_backtest_accounts_for_fees_slippage_and_funding() -> None:
    candles = make_candles(4, step=Decimal("0"))
    config = BacktestConfig(target_risk_reward=Decimal("100"))
    result = Backtester(OneLongSignal(), config).run(
        candles, funding_rates={candles[2].start_ms: Decimal("0.001")}
    )
    trade = result.trades[0]
    assert trade.fees > 0
    assert trade.funding_pnl < 0
    assert trade.entry_price > candles[2].open


def test_walk_forward_keeps_train_and_test_periods_separate() -> None:
    candles = make_candles(170)
    folds = walk_forward(
        candles,
        parameter_grid=[StrategyParameters(), StrategyParameters(breakout_volume_ratio=2.0)],
        train_size=80,
        test_size=30,
        step_size=30,
    )
    assert len(folds) == 3
    assert all(fold.train_end_ms < fold.test_start_ms for fold in folds)
