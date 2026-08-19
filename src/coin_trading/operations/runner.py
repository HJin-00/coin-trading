from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from coin_trading.domain import AccountState, Side, TradeProposal
from coin_trading.execution.models import OrderIntent
from coin_trading.market_data.models import Candle
from coin_trading.operations.paper import PaperBroker
from coin_trading.operations.state import PaperStateStore
from coin_trading.risk import RiskEngine
from coin_trading.strategy.signals import Signal


class RunnerStrategy(Protocol):
    minimum_history: int

    def evaluate(self, candles: list[Candle]) -> Signal: ...


class PaperTradingRunner:
    """Consumes each confirmed candle once and enters queued signals at the next open."""

    def __init__(
        self,
        *,
        broker: PaperBroker,
        strategy: RunnerStrategy,
        risk_engine: RiskEngine,
        state_store: PaperStateStore,
        history: list[Candle],
        stop_atr_multiple: Decimal = Decimal("2"),
        target_risk_reward: Decimal = Decimal("2"),
    ) -> None:
        if any(not candle.confirmed for candle in history):
            raise ValueError("runner history must contain confirmed candles only")
        self.broker = broker
        self.strategy = strategy
        self.risk_engine = risk_engine
        self.state_store = state_store
        self.history = list(history[-500:])
        self.stop_atr_multiple = stop_atr_multiple
        self.target_risk_reward = target_risk_reward
        self.pending_signal: Signal | None = None
        self.last_processed_ms = self.history[-1].start_ms if self.history else -1

    def on_candle(self, candle: Candle) -> None:
        if not candle.confirmed:
            raise ValueError("runner requires confirmed candles")
        if candle.start_ms == self.last_processed_ms:
            return
        if candle.start_ms < self.last_processed_ms:
            raise ValueError("out-of-order candle")

        if self.pending_signal is not None and self.broker.position is None:
            self._enter_pending(candle)
        self.broker.on_candle(candle)
        self.history.append(candle)
        self.history = self.history[-500:]
        self.last_processed_ms = candle.start_ms
        if len(self.history) >= self.strategy.minimum_history:
            signal = self.strategy.evaluate(self.history)
            self.pending_signal = None if signal.side is Side.NO_TRADE else signal
            self.broker.audit.record(
                "strategy_signal",
                symbol=candle.symbol,
                side=signal.side.value,
                reason=signal.reason,
                data_end_ms=signal.indicators.timestamp_ms,
            )
        self._save_state()

    def _enter_pending(self, candle: Candle) -> None:
        signal = self.pending_signal
        assert signal is not None
        entry = Decimal(candle.open)
        stop_distance = Decimal(str(signal.indicators.atr)) * self.stop_atr_multiple
        if signal.side is Side.LONG:
            stop = entry - stop_distance
            target = entry + stop_distance * self.target_risk_reward
        else:
            stop = entry + stop_distance
            target = entry - stop_distance * self.target_risk_reward
        proposal = TradeProposal(candle.symbol, signal.side, entry, stop)
        account = AccountState(
            equity=self.broker.equity,
            daily_pnl=self.broker.daily_pnl,
            open_positions=0,
        )
        decision = self.risk_engine.evaluate(proposal, account)
        self.pending_signal = None
        if not decision.approved:
            self.broker.audit.record("paper_order_rejected", reason=decision.reason)
            return
        intent = OrderIntent(
            symbol=candle.symbol,
            side=signal.side,
            quantity=decision.quantity,
            expected_entry_price=entry,
            stop_price=stop,
            take_profit_price=target,
            idempotency_key=f"paper:{candle.symbol}:{candle.interval}:{candle.start_ms}",
        )
        self.broker.submit(intent, market_price=entry, timestamp_ms=candle.start_ms)

    def _save_state(self) -> None:
        self.state_store.save(
            {
                "broker": self.broker.export_state(),
                "last_processed_ms": self.last_processed_ms,
            }
        )
