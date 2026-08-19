from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from typing import Protocol

from coin_trading.domain import Side
from coin_trading.market_data.models import Candle
from coin_trading.strategy.signals import BaselineStrategy, Signal


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    initial_equity: Decimal = Decimal("10000")
    risk_per_trade: Decimal = Decimal("0.01")
    max_position_fraction: Decimal = Decimal("0.30")
    stop_atr_multiple: Decimal = Decimal("2")
    target_risk_reward: Decimal = Decimal("2")
    fee_rate: Decimal = Decimal("0.00055")
    slippage_bps: Decimal = Decimal("2")

    def validate(self) -> None:
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if not Decimal("0") < self.risk_per_trade <= Decimal("0.02"):
            raise ValueError("risk_per_trade must be in (0, 0.02]")
        if not Decimal("0") < self.max_position_fraction <= Decimal("0.50"):
            raise ValueError("max_position_fraction must be in (0, 0.50]")
        if self.stop_atr_multiple <= 0 or self.target_risk_reward <= 0:
            raise ValueError("stop and target multiples must be positive")
        if self.fee_rate < 0 or self.slippage_bps < 0:
            raise ValueError("cost assumptions cannot be negative")


@dataclass(frozen=True, slots=True)
class Trade:
    side: Side
    entry_time_ms: int
    exit_time_ms: int
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    fees: Decimal
    funding_pnl: Decimal
    net_pnl: Decimal
    exit_reason: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    initial_equity: Decimal
    final_equity: Decimal
    total_return: float
    max_drawdown: float
    win_rate: float
    average_win_loss_ratio: float
    sharpe: float
    trades: tuple[Trade, ...]
    equity_curve: tuple[Decimal, ...]


class Strategy(Protocol):
    minimum_history: int

    def evaluate(self, candles: list[Candle]) -> Signal: ...


@dataclass(slots=True)
class _Position:
    side: Side
    entry_time_ms: int
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    quantity: Decimal
    entry_fee: Decimal
    funding_pnl: Decimal = Decimal("0")


class Backtester:
    """Single-position, next-bar execution with conservative intrabar ordering."""

    def __init__(
        self,
        strategy: Strategy | None = None,
        config: BacktestConfig | None = None,
    ) -> None:
        self.strategy = strategy or BaselineStrategy()
        self.config = config or BacktestConfig()
        self.config.validate()

    def run(
        self,
        candles: list[Candle],
        *,
        funding_rates: Mapping[int, Decimal] | None = None,
    ) -> BacktestResult:
        if len(candles) <= self.strategy.minimum_history:
            raise ValueError("not enough candles to run backtest")
        if any(not candle.confirmed for candle in candles):
            raise ValueError("backtest requires confirmed candles only")
        if any(
            current.start_ms <= previous.start_ms
            for previous, current in zip(candles, candles[1:], strict=False)
        ):
            raise ValueError("candles must be strictly ascending")

        funding_rates = funding_rates or {}
        cash = self.config.initial_equity
        position: _Position | None = None
        pending_signal: Signal | None = None
        trades: list[Trade] = []
        equity_curve: list[Decimal] = []

        for index, candle in enumerate(candles):
            if pending_signal is not None and position is None:
                position = self._open_position(pending_signal, candle, cash)
                if position is not None:
                    cash -= position.entry_fee
                pending_signal = None

            if position is not None:
                rate = funding_rates.get(candle.start_ms)
                if rate is not None:
                    direction = Decimal("1") if position.side is Side.LONG else Decimal("-1")
                    payment = -(direction * position.entry_price * position.quantity * rate)
                    position.funding_pnl += payment
                    cash += payment
                exit_price, exit_reason = self._exit_for_candle(position, candle)
                if exit_price is not None:
                    trade = self._close_position(position, candle, exit_price, exit_reason)
                    cash += trade.gross_pnl - (trade.fees - position.entry_fee)
                    trades.append(trade)
                    position = None

            equity_curve.append(cash + self._unrealized(position, Decimal(candle.close)))
            enough_history = index + 1 >= self.strategy.minimum_history
            if position is None and enough_history and index < len(candles) - 1:
                signal = self.strategy.evaluate(candles[: index + 1])
                if signal.side is not Side.NO_TRADE:
                    pending_signal = signal

        if position is not None:
            last = candles[-1]
            exit_price = self._slipped_price(Decimal(last.close), position.side, entering=False)
            trade = self._close_position(position, last, exit_price, "end_of_data")
            cash += trade.gross_pnl - (trade.fees - position.entry_fee)
            trades.append(trade)
            equity_curve[-1] = cash

        return self._result(cash, trades, equity_curve)

    def _open_position(
        self, signal: Signal, candle: Candle, equity: Decimal
    ) -> _Position | None:
        entry = self._slipped_price(Decimal(candle.open), signal.side, entering=True)
        stop_distance = Decimal(str(signal.indicators.atr)) * self.config.stop_atr_multiple
        if stop_distance <= 0:
            return None
        risk_quantity = equity * self.config.risk_per_trade / stop_distance
        capped_quantity = equity * self.config.max_position_fraction / entry
        quantity = min(risk_quantity, capped_quantity)
        if quantity <= 0:
            return None
        if signal.side is Side.LONG:
            stop = entry - stop_distance
            target = entry + stop_distance * self.config.target_risk_reward
        else:
            stop = entry + stop_distance
            target = entry - stop_distance * self.config.target_risk_reward
        if stop <= 0 or target <= 0:
            return None
        return _Position(
            side=signal.side,
            entry_time_ms=candle.start_ms,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            quantity=quantity,
            entry_fee=entry * quantity * self.config.fee_rate,
        )

    def _exit_for_candle(
        self, position: _Position, candle: Candle
    ) -> tuple[Decimal | None, str]:
        open_price = Decimal(candle.open)
        high = Decimal(candle.high)
        low = Decimal(candle.low)
        if position.side is Side.LONG:
            if low <= position.stop_price:
                raw = min(open_price, position.stop_price)
                return self._slipped_price(raw, position.side, entering=False), "stop"
            if high >= position.target_price:
                raw = max(open_price, position.target_price)
                return self._slipped_price(raw, position.side, entering=False), "target"
        else:
            if high >= position.stop_price:
                raw = max(open_price, position.stop_price)
                return self._slipped_price(raw, position.side, entering=False), "stop"
            if low <= position.target_price:
                raw = min(open_price, position.target_price)
                return self._slipped_price(raw, position.side, entering=False), "target"
        return None, ""

    def _close_position(
        self,
        position: _Position,
        candle: Candle,
        exit_price: Decimal,
        reason: str,
    ) -> Trade:
        direction = Decimal("1") if position.side is Side.LONG else Decimal("-1")
        gross = direction * (exit_price - position.entry_price) * position.quantity
        exit_fee = exit_price * position.quantity * self.config.fee_rate
        fees = position.entry_fee + exit_fee
        return Trade(
            side=position.side,
            entry_time_ms=position.entry_time_ms,
            exit_time_ms=candle.end_ms,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            gross_pnl=gross,
            fees=fees,
            funding_pnl=position.funding_pnl,
            net_pnl=gross - fees + position.funding_pnl,
            exit_reason=reason,
        )

    def _slipped_price(self, price: Decimal, side: Side, *, entering: bool) -> Decimal:
        fraction = self.config.slippage_bps / Decimal("10000")
        adverse_up = (side is Side.LONG) == entering
        return price * (Decimal("1") + fraction if adverse_up else Decimal("1") - fraction)

    @staticmethod
    def _unrealized(position: _Position | None, close: Decimal) -> Decimal:
        if position is None:
            return Decimal("0")
        direction = Decimal("1") if position.side is Side.LONG else Decimal("-1")
        return direction * (close - position.entry_price) * position.quantity

    def _result(
        self, final_equity: Decimal, trades: list[Trade], equity_curve: list[Decimal]
    ) -> BacktestResult:
        returns = [
            float(current / previous - 1)
            for previous, current in zip(equity_curve, equity_curve[1:], strict=False)
            if previous != 0
        ]
        peak = equity_curve[0]
        max_drawdown = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, float((peak - equity) / peak))
        wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
        losses = [-trade.net_pnl for trade in trades if trade.net_pnl < 0]
        ratio = 0.0
        if wins and losses:
            ratio = float((sum(wins) / len(wins)) / (sum(losses) / len(losses)))
        sharpe = 0.0
        if len(returns) > 1:
            mean = sum(returns) / len(returns)
            variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
            if variance > 0:
                sharpe = mean / sqrt(variance) * sqrt(len(returns))
        return BacktestResult(
            initial_equity=self.config.initial_equity,
            final_equity=final_equity,
            total_return=float(final_equity / self.config.initial_equity - 1),
            max_drawdown=max_drawdown,
            win_rate=0.0 if not trades else len(wins) / len(trades),
            average_win_loss_ratio=ratio,
            sharpe=sharpe,
            trades=tuple(trades),
            equity_curve=tuple(equity_curve),
        )
