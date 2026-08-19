from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    side: Side
    entry_price: Decimal
    stop_price: Decimal | None
    leverage: Decimal = Decimal("1")


@dataclass(frozen=True)
class AccountState:
    equity: Decimal
    daily_pnl: Decimal
    open_positions: int


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    quantity: Decimal = Decimal("0")
    notional: Decimal = Decimal("0")

