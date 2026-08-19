from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    interval: str
    start_ms: int
    end_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal
    confirmed: bool

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("open", "high", "low", "close", "volume", "turnover"):
            values[key] = str(values[key])
        return values


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    timestamp_ms: int
    funding_rate: Decimal | None
    open_interest: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp_ms": self.timestamp_ms,
            "funding_rate": None if self.funding_rate is None else str(self.funding_rate),
            "open_interest": None if self.open_interest is None else str(self.open_interest),
        }
