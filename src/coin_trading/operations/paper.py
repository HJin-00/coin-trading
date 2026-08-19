from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from coin_trading.domain import Side
from coin_trading.execution.models import OrderIntent
from coin_trading.market_data.models import Candle
from coin_trading.operations.audit import AuditLogger
from coin_trading.operations.safety import KillSwitch, TradingHalted


@dataclass(frozen=True, slots=True)
class PaperPosition:
    symbol: str
    side: Side
    quantity: Decimal
    entry_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    entry_time_ms: int
    entry_fee: Decimal


@dataclass(frozen=True, slots=True)
class PaperTrade:
    symbol: str
    side: Side
    entry_time_ms: int
    exit_time_ms: int
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    fees: Decimal
    net_pnl: Decimal
    exit_reason: str


class PaperBroker:
    """Forward-paper broker driven only by confirmed mainnet public candles."""

    def __init__(
        self,
        *,
        initial_equity: Decimal,
        kill_switch: KillSwitch,
        audit: AuditLogger,
        fee_rate: Decimal = Decimal("0.00055"),
        slippage_bps: Decimal = Decimal("2"),
        daily_loss_limit: Decimal = Decimal("0.03"),
    ) -> None:
        if initial_equity <= 0:
            raise ValueError("initial equity must be positive")
        if not Decimal("0") < daily_loss_limit <= Decimal("0.05"):
            raise ValueError("daily loss limit must be in (0, 0.05]")
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.kill_switch = kill_switch
        self.audit = audit
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.daily_loss_limit = daily_loss_limit
        self.position: PaperPosition | None = None
        self.trades: list[PaperTrade] = []
        self._day: int | None = None
        self._day_start_equity = initial_equity

    @property
    def daily_pnl(self) -> Decimal:
        return self.equity - self._day_start_equity

    def export_state(self) -> dict[str, Any]:
        position = None
        if self.position is not None:
            position = {
                "symbol": self.position.symbol,
                "side": self.position.side.value,
                "quantity": str(self.position.quantity),
                "entry_price": str(self.position.entry_price),
                "stop_price": str(self.position.stop_price),
                "take_profit_price": str(self.position.take_profit_price),
                "entry_time_ms": self.position.entry_time_ms,
                "entry_fee": str(self.position.entry_fee),
            }
        trades = [
            {
                "symbol": trade.symbol,
                "side": trade.side.value,
                "entry_time_ms": trade.entry_time_ms,
                "exit_time_ms": trade.exit_time_ms,
                "entry_price": str(trade.entry_price),
                "exit_price": str(trade.exit_price),
                "quantity": str(trade.quantity),
                "fees": str(trade.fees),
                "net_pnl": str(trade.net_pnl),
                "exit_reason": trade.exit_reason,
            }
            for trade in self.trades
        ]
        return {
            "equity": str(self.equity),
            "position": position,
            "trades": trades,
            "day": self._day,
            "day_start_equity": str(self._day_start_equity),
        }

    def restore_state(self, payload: dict[str, Any]) -> None:
        equity = Decimal(str(payload["equity"]))
        if equity <= 0:
            raise ValueError("restored equity must be positive")
        self.equity = equity
        position = payload.get("position")
        self.position = None
        if position is not None:
            self.position = PaperPosition(
                symbol=str(position["symbol"]),
                side=Side(str(position["side"])),
                quantity=Decimal(str(position["quantity"])),
                entry_price=Decimal(str(position["entry_price"])),
                stop_price=Decimal(str(position["stop_price"])),
                take_profit_price=Decimal(str(position["take_profit_price"])),
                entry_time_ms=int(position["entry_time_ms"]),
                entry_fee=Decimal(str(position["entry_fee"])),
            )
        self.trades = [
            PaperTrade(
                symbol=str(trade["symbol"]),
                side=Side(str(trade["side"])),
                entry_time_ms=int(trade["entry_time_ms"]),
                exit_time_ms=int(trade["exit_time_ms"]),
                entry_price=Decimal(str(trade["entry_price"])),
                exit_price=Decimal(str(trade["exit_price"])),
                quantity=Decimal(str(trade["quantity"])),
                fees=Decimal(str(trade["fees"])),
                net_pnl=Decimal(str(trade["net_pnl"])),
                exit_reason=str(trade["exit_reason"]),
            )
            for trade in payload.get("trades", [])
        ]
        day = payload.get("day")
        self._day = None if day is None else int(day)
        self._day_start_equity = Decimal(str(payload["day_start_equity"]))

    def submit(
        self,
        intent: OrderIntent,
        *,
        market_price: Decimal,
        timestamp_ms: int,
    ) -> PaperPosition:
        self.kill_switch.ensure_trading_allowed()
        intent.validate()
        if self.position is not None:
            raise TradingHalted("paper broker allows one position at a time")
        self._roll_day(timestamp_ms)
        entry = self._slipped(market_price, intent.side, entering=True)
        fee = entry * intent.quantity * self.fee_rate
        self.equity -= fee
        self.position = PaperPosition(
            intent.symbol,
            intent.side,
            intent.quantity,
            entry,
            intent.stop_price,
            intent.take_profit_price,
            timestamp_ms,
            fee,
        )
        self.audit.record(
            "paper_position_opened",
            symbol=intent.symbol,
            side=intent.side.value,
            quantity=str(intent.quantity),
            entry_price=str(entry),
            stop_price=str(intent.stop_price),
            take_profit_price=str(intent.take_profit_price),
        )
        return self.position

    def on_candle(self, candle: Candle) -> PaperTrade | None:
        if not candle.confirmed:
            raise ValueError("paper execution requires a confirmed candle")
        self._roll_day(candle.start_ms)
        position = self.position
        if position is None or candle.symbol != position.symbol:
            return None
        exit_price: Decimal | None = None
        reason = ""
        if position.side is Side.LONG:
            if candle.low <= position.stop_price:
                exit_price, reason = min(candle.open, position.stop_price), "stop"
            elif candle.high >= position.take_profit_price:
                exit_price, reason = max(candle.open, position.take_profit_price), "target"
        else:
            if candle.high >= position.stop_price:
                exit_price, reason = max(candle.open, position.stop_price), "stop"
            elif candle.low <= position.take_profit_price:
                exit_price, reason = min(candle.open, position.take_profit_price), "target"
        if exit_price is None:
            return None
        exit_price = self._slipped(exit_price, position.side, entering=False)
        direction = Decimal("1") if position.side is Side.LONG else Decimal("-1")
        gross = direction * (exit_price - position.entry_price) * position.quantity
        exit_fee = exit_price * position.quantity * self.fee_rate
        net = gross - position.entry_fee - exit_fee
        self.equity += gross - exit_fee
        trade = PaperTrade(
            position.symbol,
            position.side,
            position.entry_time_ms,
            candle.end_ms,
            position.entry_price,
            exit_price,
            position.quantity,
            position.entry_fee + exit_fee,
            net,
            reason,
        )
        self.trades.append(trade)
        self.position = None
        self.audit.record(
            "paper_position_closed",
            symbol=trade.symbol,
            net_pnl=str(trade.net_pnl),
            exit_reason=trade.exit_reason,
            equity=str(self.equity),
        )
        self._enforce_daily_loss()
        return trade

    def _roll_day(self, timestamp_ms: int) -> None:
        day = timestamp_ms // 86_400_000
        if self._day != day:
            self._day = day
            self._day_start_equity = self.equity

    def _enforce_daily_loss(self) -> None:
        loss = self._day_start_equity - self.equity
        if loss >= self._day_start_equity * self.daily_loss_limit:
            self.kill_switch.engage("daily paper loss limit reached")
            self.audit.record("kill_switch_engaged", reason="daily paper loss limit reached")

    def _slipped(self, price: Decimal, side: Side, *, entering: bool) -> Decimal:
        fraction = self.slippage_bps / Decimal("10000")
        adverse_up = (side is Side.LONG) == entering
        return price * (Decimal("1") + fraction if adverse_up else Decimal("1") - fraction)
