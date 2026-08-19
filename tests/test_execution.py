from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from coin_trading.domain import Side
from coin_trading.execution import (
    BybitExecutionError,
    BybitTestnetExecutor,
    OrderIntent,
    OrderState,
    OrderStateMachine,
    OrderType,
    ProtectionState,
)


def response(items: list[dict[str, Any]] | None = None, **result: Any) -> dict[str, Any]:
    if items is not None:
        result["list"] = items
    return {"retCode": 0, "retMsg": "OK", "result": result}


class FakeClient:
    def __init__(self) -> None:
        self.positions: list[dict[str, Any]] = []
        self.open_orders: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.placed: list[dict[str, Any]] = []
        self.leverage: list[dict[str, Any]] = []

    def get_positions(self, **kwargs: Any) -> dict[str, Any]:
        return response(self.positions)

    def get_open_orders(self, **kwargs: Any) -> dict[str, Any]:
        return response(self.open_orders)

    def get_order_history(self, **kwargs: Any) -> dict[str, Any]:
        return response(self.history)

    def get_instruments_info(self, **kwargs: Any) -> dict[str, Any]:
        return response(
            [
                {
                    "priceFilter": {"tickSize": "0.5"},
                    "lotSizeFilter": {
                        "qtyStep": "0.001",
                        "minOrderQty": "0.001",
                        "minNotionalValue": "5",
                    },
                }
            ]
        )

    def set_leverage(self, **kwargs: Any) -> dict[str, Any]:
        self.leverage.append(kwargs)
        return response()

    def place_order(self, **kwargs: Any) -> dict[str, Any]:
        self.placed.append(kwargs)
        return response(orderId="order-1", orderLinkId=kwargs["orderLinkId"])


def long_intent() -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSDT",
        side=Side.LONG,
        quantity=Decimal("0.0109"),
        expected_entry_price=Decimal("50000"),
        stop_price=Decimal("49000.1"),
        take_profit_price=Decimal("52000.4"),
        idempotency_key="signal-2026-08-19T00:00:00Z",
        leverage=Decimal("2"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("49999.9"),
    )


def test_executor_cannot_run_on_mainnet() -> None:
    with pytest.raises(BybitExecutionError, match="testnet"):
        BybitTestnetExecutor(FakeClient(), testnet=False)


def test_recovery_is_required_before_order_submission() -> None:
    executor = BybitTestnetExecutor(FakeClient(), testnet=True)
    with pytest.raises(BybitExecutionError, match="recovery"):
        executor.submit(long_intent())


def test_unprotected_recovered_position_blocks_new_orders() -> None:
    client = FakeClient()
    client.positions = [
        {"symbol": "BTCUSDT", "size": "0.01", "stopLoss": "", "takeProfit": "52000"}
    ]
    executor = BybitTestnetExecutor(client, testnet=True)
    report = executor.recover()
    assert report.trading_blocked
    assert report.unprotected_symbols == ("BTCUSDT",)
    with pytest.raises(BybitExecutionError, match="blocked"):
        executor.submit(long_intent())


def test_submission_normalizes_values_and_attaches_full_protection() -> None:
    client = FakeClient()
    executor = BybitTestnetExecutor(client, testnet=True)
    assert not executor.recover().trading_blocked
    submission = executor.submit(long_intent())
    placed = client.placed[0]
    assert submission.quantity == Decimal("0.010")
    assert placed["price"] == "49999.5"
    assert placed["stopLoss"] == "49000.5"
    assert placed["takeProfit"] == "52000.0"
    assert placed["tpslMode"] == "Full"
    assert placed["slOrderType"] == "Market"
    assert len(placed["orderLinkId"]) <= 36


def test_idempotent_retry_reuses_existing_order() -> None:
    client = FakeClient()
    client.open_orders = [{"orderId": "existing-1"}]
    executor = BybitTestnetExecutor(client, testnet=True)
    executor.recover()
    submission = executor.submit(long_intent())
    assert submission.reused_existing
    assert submission.order_id == "existing-1"
    assert not client.placed


def test_terminal_order_state_cannot_regress() -> None:
    states = OrderStateMachine()
    assert states.update("order-1", "New") is OrderState.OPEN
    assert states.update("order-1", "Filled") is OrderState.FILLED
    with pytest.raises(ValueError, match="terminal"):
        states.update("order-1", "New")


def test_missing_protection_after_fill_blocks_executor() -> None:
    client = FakeClient()
    executor = BybitTestnetExecutor(client, testnet=True)
    executor.recover()
    client.positions = [
        {"symbol": "BTCUSDT", "size": "0.01", "stopLoss": "", "takeProfit": "52000"}
    ]
    assert executor.verify_position_protection("BTCUSDT") is ProtectionState.MISSING
    with pytest.raises(BybitExecutionError, match="blocked"):
        executor.submit(long_intent())
