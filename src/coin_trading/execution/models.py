from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

from coin_trading.domain import Side


class OrderType(StrEnum):
    MARKET = "Market"
    LIMIT = "Limit"


class ProtectionState(StrEnum):
    WAITING_FOR_FILL = "WAITING_FOR_FILL"
    PROTECTED = "PROTECTED"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    symbol: str
    side: Side
    quantity: Decimal
    expected_entry_price: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    idempotency_key: str
    leverage: Decimal = Decimal("1")
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None

    def validate(self) -> None:
        if self.side is Side.NO_TRADE:
            raise ValueError("NO_TRADE cannot become an order")
        if not self.symbol.endswith("USDT") or not self.symbol.isalnum():
            raise ValueError("only path-safe USDT symbols are supported")
        if self.quantity <= 0 or self.expected_entry_price <= 0:
            raise ValueError("quantity and entry price must be positive")
        if self.stop_price <= 0 or self.take_profit_price <= 0:
            raise ValueError("protective prices must be positive")
        if self.side is Side.LONG and not (
            self.stop_price < self.expected_entry_price < self.take_profit_price
        ):
            raise ValueError("long protection must satisfy stop < entry < target")
        if self.side is Side.SHORT and not (
            self.take_profit_price < self.expected_entry_price < self.stop_price
        ):
            raise ValueError("short protection must satisfy target < entry < stop")
        if self.leverage <= 0 or self.leverage > 3:
            raise ValueError("leverage must be in (0, 3]")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")


@dataclass(frozen=True, slots=True)
class InstrumentRules:
    tick_size: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal
    minimum_notional: Decimal

    def __post_init__(self) -> None:
        if min(
            self.tick_size,
            self.quantity_step,
            self.minimum_quantity,
        ) <= 0 or self.minimum_notional < 0:
            raise ValueError("instrument rules must be positive")

    def floor_quantity(self, value: Decimal) -> Decimal:
        steps = (value / self.quantity_step).to_integral_value(rounding=ROUND_FLOOR)
        return steps * self.quantity_step

    def floor_price(self, value: Decimal) -> Decimal:
        return (value / self.tick_size).to_integral_value(rounding=ROUND_FLOOR) * self.tick_size

    def ceil_price(self, value: Decimal) -> Decimal:
        return (value / self.tick_size).to_integral_value(rounding=ROUND_CEILING) * self.tick_size


@dataclass(frozen=True, slots=True)
class OrderSubmission:
    order_id: str
    order_link_id: str
    quantity: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    reused_existing: bool


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    open_positions: int
    open_orders: int
    unprotected_symbols: tuple[str, ...]

    @property
    def trading_blocked(self) -> bool:
        return bool(self.unprotected_symbols)
