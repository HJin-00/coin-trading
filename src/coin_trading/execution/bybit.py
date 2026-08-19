from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from coin_trading.domain import Side
from coin_trading.execution.environment import ExecutionEnvironment
from coin_trading.execution.models import (
    InstrumentRules,
    OrderIntent,
    OrderSubmission,
    OrderType,
    ProtectionState,
    RecoveryReport,
)


class BybitExecutionError(RuntimeError):
    """Raised when an execution safety invariant or Bybit request fails."""


class BybitTradingClient(Protocol):
    def get_instruments_info(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_open_orders(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_order_history(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_positions(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def set_leverage(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def place_order(self, **kwargs: Any) -> Mapping[str, Any]: ...


def _result(response: Mapping[str, Any]) -> Mapping[str, Any]:
    if response.get("retCode") != 0:
        raise BybitExecutionError(
            f"Bybit error {response.get('retCode')}: {response.get('retMsg')}"
        )
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise BybitExecutionError("Bybit response has no result object")
    return cast(Mapping[str, Any], result)


def _items(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = _result(response).get("list")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise BybitExecutionError("Bybit response has no result list")
    if not all(isinstance(value, Mapping) for value in values):
        raise BybitExecutionError("Bybit result list contains an invalid item")
    return [cast(Mapping[str, Any], value) for value in values]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BybitExecutionError(f"invalid decimal in {field}") from exc


def _text(value: Decimal) -> str:
    return format(value, "f")


class BybitExecutionAdapter:
    """One-way USDT perpetual adapter restricted to non-live environments."""

    def __init__(
        self,
        client: BybitTradingClient,
        *,
        environment: ExecutionEnvironment,
    ) -> None:
        if environment is ExecutionEnvironment.LOCAL_PAPER:
            raise BybitExecutionError("local paper execution does not use a Bybit trading client")
        self.client = client
        self.environment = environment
        self._recovery_completed = False
        self._trading_blocked = True
        self._rules: dict[str, InstrumentRules] = {}

    def recover(self) -> RecoveryReport:
        positions = _items(self.client.get_positions(category="linear", settleCoin="USDT"))
        orders = _items(
            self.client.get_open_orders(
                category="linear", settleCoin="USDT", openOnly=0, limit=50
            )
        )
        active_positions = [
            position
            for position in positions
            if _decimal(position.get("size", 0), "size") > 0
        ]
        unprotected = tuple(
            sorted(
                str(position.get("symbol", ""))
                for position in active_positions
                if _decimal(position.get("stopLoss") or 0, "stopLoss") <= 0
                or _decimal(position.get("takeProfit") or 0, "takeProfit") <= 0
            )
        )
        report = RecoveryReport(len(active_positions), len(orders), unprotected)
        self._recovery_completed = True
        self._trading_blocked = report.trading_blocked
        return report

    def submit(self, intent: OrderIntent) -> OrderSubmission:
        intent.validate()
        if not self._recovery_completed:
            raise BybitExecutionError("recovery must complete before submitting an order")
        if self._trading_blocked:
            raise BybitExecutionError("trading is blocked by an unprotected recovered position")

        symbol = intent.symbol.upper()
        rules = self.instrument_rules(symbol)
        quantity = rules.floor_quantity(intent.quantity)
        if quantity < rules.minimum_quantity:
            raise BybitExecutionError("normalized quantity is below the instrument minimum")
        if quantity * intent.expected_entry_price < rules.minimum_notional:
            raise BybitExecutionError("normalized order is below the minimum notional")
        stop, target = self._protective_prices(intent, rules)
        link_id = self._order_link_id(intent.idempotency_key)
        existing = self._find_existing(symbol, link_id)
        if existing is not None:
            return OrderSubmission(
                order_id=str(existing.get("orderId", "")),
                order_link_id=link_id,
                quantity=quantity,
                stop_price=stop,
                take_profit_price=target,
                reused_existing=True,
            )

        if self.environment is ExecutionEnvironment.DEMO and intent.leverage != 1:
            raise BybitExecutionError("Demo Trading requires preconfigured 1x leverage")
        if self.environment is ExecutionEnvironment.TESTNET:
            leverage = _text(intent.leverage)
            _result(
                self.client.set_leverage(
                    category="linear",
                    symbol=symbol,
                    buyLeverage=leverage,
                    sellLeverage=leverage,
                )
            )
        parameters: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "side": "Buy" if intent.side is Side.LONG else "Sell",
            "orderType": intent.order_type.value,
            "qty": _text(quantity),
            "timeInForce": "IOC" if intent.order_type is OrderType.MARKET else "GTC",
            "positionIdx": 0,
            "orderLinkId": link_id,
            "reduceOnly": False,
            "takeProfit": _text(target),
            "stopLoss": _text(stop),
            "tpTriggerBy": "MarkPrice",
            "slTriggerBy": "MarkPrice",
            "tpslMode": "Full",
            "tpOrderType": "Market",
            "slOrderType": "Market",
        }
        if intent.order_type is OrderType.LIMIT:
            assert intent.limit_price is not None
            limit_price = (
                rules.floor_price(intent.limit_price)
                if intent.side is Side.LONG
                else rules.ceil_price(intent.limit_price)
            )
            parameters["price"] = _text(limit_price)
        result = _result(self.client.place_order(**parameters))
        order_id = str(result.get("orderId", ""))
        if not order_id:
            raise BybitExecutionError("Bybit accepted the request without an order id")
        return OrderSubmission(order_id, link_id, quantity, stop, target, False)

    def verify_position_protection(self, symbol: str) -> ProtectionState:
        positions = _items(
            self.client.get_positions(category="linear", symbol=symbol.upper())
        )
        active = [
            position
            for position in positions
            if _decimal(position.get("size", 0), "size") > 0
        ]
        if not active:
            return ProtectionState.WAITING_FOR_FILL
        protected = all(
            _decimal(position.get("stopLoss") or 0, "stopLoss") > 0
            and _decimal(position.get("takeProfit") or 0, "takeProfit") > 0
            for position in active
        )
        if protected:
            return ProtectionState.PROTECTED
        self._trading_blocked = True
        return ProtectionState.MISSING

    def instrument_rules(self, symbol: str) -> InstrumentRules:
        if symbol in self._rules:
            return self._rules[symbol]
        items = _items(
            self.client.get_instruments_info(category="linear", symbol=symbol)
        )
        if len(items) != 1:
            raise BybitExecutionError(f"instrument rules not found for {symbol}")
        price_filter = items[0].get("priceFilter")
        lot_filter = items[0].get("lotSizeFilter")
        if not isinstance(price_filter, Mapping) or not isinstance(lot_filter, Mapping):
            raise BybitExecutionError("instrument filters are missing")
        rules = InstrumentRules(
            tick_size=_decimal(price_filter.get("tickSize"), "tickSize"),
            quantity_step=_decimal(lot_filter.get("qtyStep"), "qtyStep"),
            minimum_quantity=_decimal(lot_filter.get("minOrderQty"), "minOrderQty"),
            minimum_notional=_decimal(lot_filter.get("minNotionalValue", 0), "minNotionalValue"),
        )
        self._rules[symbol] = rules
        return rules

    def _find_existing(self, symbol: str, link_id: str) -> Mapping[str, Any] | None:
        open_orders = _items(
            self.client.get_open_orders(
                category="linear", symbol=symbol, orderLinkId=link_id
            )
        )
        if open_orders:
            return open_orders[0]
        history = _items(
            self.client.get_order_history(
                category="linear", symbol=symbol, orderLinkId=link_id, limit=1
            )
        )
        return history[0] if history else None

    @staticmethod
    def _order_link_id(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:30]
        return f"ct-{digest}"

    @staticmethod
    def _protective_prices(
        intent: OrderIntent, rules: InstrumentRules
    ) -> tuple[Decimal, Decimal]:
        if intent.side is Side.LONG:
            stop = rules.ceil_price(intent.stop_price)
            target = rules.floor_price(intent.take_profit_price)
            valid = stop < intent.expected_entry_price < target
        else:
            stop = rules.floor_price(intent.stop_price)
            target = rules.ceil_price(intent.take_profit_price)
            valid = target < intent.expected_entry_price < stop
        if not valid:
            raise BybitExecutionError("normalized protective prices cross the expected entry")
        return stop, target


class BybitTestnetExecutor(BybitExecutionAdapter):
    def __init__(self, client: BybitTradingClient, *, testnet: bool) -> None:
        if not testnet:
            raise BybitExecutionError("this adapter is restricted to Bybit testnet")
        super().__init__(client, environment=ExecutionEnvironment.TESTNET)


class BybitDemoExecutor(BybitExecutionAdapter):
    """Mainnet Demo Trading adapter; the caller must use api-demo.bybit.com credentials."""

    def __init__(self, client: BybitTradingClient) -> None:
        super().__init__(client, environment=ExecutionEnvironment.DEMO)
