from __future__ import annotations

from enum import StrEnum


class OrderState(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


STATUS_MAP = {
    "Created": OrderState.PENDING,
    "New": OrderState.OPEN,
    "PartiallyFilled": OrderState.PARTIALLY_FILLED,
    "Filled": OrderState.FILLED,
    "Cancelled": OrderState.CANCELLED,
    "Deactivated": OrderState.CANCELLED,
    "Rejected": OrderState.REJECTED,
}
TERMINAL_STATES = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}


class OrderStateMachine:
    def __init__(self) -> None:
        self._states: dict[str, OrderState] = {}

    def update(self, order_id: str, bybit_status: str) -> OrderState:
        try:
            new_state = STATUS_MAP[bybit_status]
        except KeyError as exc:
            raise ValueError(f"unsupported Bybit order status: {bybit_status}") from exc
        current = self._states.get(order_id)
        if current in TERMINAL_STATES and new_state is not current:
            raise ValueError(f"terminal order {order_id} cannot transition from {current}")
        self._states[order_id] = new_state
        return new_state

    def state(self, order_id: str) -> OrderState | None:
        return self._states.get(order_id)
