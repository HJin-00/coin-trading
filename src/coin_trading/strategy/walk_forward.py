from __future__ import annotations

from dataclasses import dataclass

from coin_trading.market_data.models import Candle
from coin_trading.strategy.backtest import BacktestConfig, Backtester, BacktestResult
from coin_trading.strategy.signals import BaselineStrategy, StrategyParameters


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    train_start_ms: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int
    parameters: StrategyParameters
    train_result: BacktestResult
    test_result: BacktestResult


def walk_forward(
    candles: list[Candle],
    *,
    parameter_grid: list[StrategyParameters],
    train_size: int,
    test_size: int,
    step_size: int | None = None,
    config: BacktestConfig | None = None,
) -> list[WalkForwardFold]:
    if not parameter_grid:
        raise ValueError("parameter_grid cannot be empty")
    minimum = BaselineStrategy.minimum_history + 1
    if train_size < minimum or test_size <= 0:
        raise ValueError("train_size is too small or test_size is not positive")
    step = step_size or test_size
    if step <= 0:
        raise ValueError("step_size must be positive")

    folds: list[WalkForwardFold] = []
    start = 0
    while start + train_size + test_size <= len(candles):
        train = candles[start : start + train_size]
        test = candles[start + train_size : start + train_size + test_size]
        candidates: list[tuple[float, StrategyParameters, BacktestResult]] = []
        for parameters in parameter_grid:
            result = Backtester(BaselineStrategy(parameters), config).run(train)
            score = result.total_return - result.max_drawdown
            candidates.append((score, parameters, result))
        _, best_parameters, train_result = max(candidates, key=lambda item: item[0])

        warmup_count = BaselineStrategy.minimum_history - 1
        warmup = train[-warmup_count:]
        test_result = Backtester(BaselineStrategy(best_parameters), config).run(warmup + test)
        folds.append(
            WalkForwardFold(
                train_start_ms=train[0].start_ms,
                train_end_ms=train[-1].end_ms,
                test_start_ms=test[0].start_ms,
                test_end_ms=test[-1].end_ms,
                parameters=best_parameters,
                train_result=train_result,
                test_result=test_result,
            )
        )
        start += step
    return folds
