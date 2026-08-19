from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from coin_trading.market_data.models import Candle, MarketSnapshot
from coin_trading.market_data.validation import DataValidationError, validate_candles

MINUTE_INTERVALS = {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720"}


class BybitAPIError(RuntimeError):
    """Raised for transport errors or non-zero Bybit response codes."""


class PublicTransport(Protocol):
    def get(self, path: str, params: Mapping[str, str | int]) -> Mapping[str, Any]: ...


class UrlLibPublicTransport:
    def __init__(self, *, testnet: bool = False, timeout_seconds: float = 10.0) -> None:
        self.base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        self.timeout_seconds = timeout_seconds

    def get(self, path: str, params: Mapping[str, str | int]) -> Mapping[str, Any]:
        request = Request(
            f"{self.base_url}{path}?{urlencode(params)}",
            headers={"User-Agent": "coin-trading/0.1"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = json.load(response)
        except (OSError, ValueError) as exc:
            raise BybitAPIError(f"Bybit request failed for {path}") from exc
        if not isinstance(payload, Mapping):
            raise BybitAPIError("Bybit returned a non-object response")
        return cast(Mapping[str, Any], payload)


def interval_to_milliseconds(interval: str | int) -> int:
    normalized = str(interval)
    if normalized not in MINUTE_INTERVALS:
        raise ValueError("only fixed minute intervals are supported")
    return int(normalized) * 60_000


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DataValidationError(f"invalid decimal in {field}") from exc


def _result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload.get("retCode") != 0:
        raise BybitAPIError(f"Bybit error {payload.get('retCode')}: {payload.get('retMsg')}")
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise BybitAPIError("Bybit response has no result object")
    return cast(Mapping[str, Any], result)


class BybitRestClient:
    """Public V5 REST client with backward kline pagination and validation."""

    def __init__(
        self,
        *,
        testnet: bool = False,
        transport: PublicTransport | None = None,
    ) -> None:
        self.transport = transport or UrlLibPublicTransport(testnet=testnet)

    def server_time_ms(self) -> int:
        result = _result(self.transport.get("/v5/market/time", {}))
        try:
            if "timeNano" in result:
                return int(str(result["timeNano"])) // 1_000_000
            return int(str(result["timeSecond"])) * 1_000
        except (KeyError, TypeError, ValueError) as exc:
            raise BybitAPIError("invalid server-time response") from exc

    def fetch_candles(
        self,
        *,
        symbol: str,
        interval: str | int,
        start_ms: int,
        end_ms: int,
        page_size: int = 1000,
    ) -> list[Candle]:
        normalized_symbol = symbol.upper()
        normalized_interval = str(interval)
        interval_ms = interval_to_milliseconds(normalized_interval)
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("end_ms must be greater than a non-negative start_ms")
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")

        server_time_ms = self.server_time_ms()
        cursor_end = end_ms - 1
        by_start: dict[int, Candle] = {}
        while cursor_end >= start_ms:
            payload = self.transport.get(
                "/v5/market/kline",
                {
                    "category": "linear",
                    "symbol": normalized_symbol,
                    "interval": normalized_interval,
                    "start": start_ms,
                    "end": cursor_end,
                    "limit": page_size,
                },
            )
            rows = _result(payload).get("list")
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                raise BybitAPIError("invalid kline list")
            if not rows:
                break

            page_starts: list[int] = []
            for row in rows:
                candle = self._parse_rest_candle(
                    row,
                    symbol=normalized_symbol,
                    interval=normalized_interval,
                    interval_ms=interval_ms,
                    server_time_ms=server_time_ms,
                )
                page_starts.append(candle.start_ms)
                if start_ms <= candle.start_ms < end_ms and candle.confirmed:
                    by_start[candle.start_ms] = candle

            oldest_start = min(page_starts)
            if oldest_start <= start_ms:
                break
            next_end = oldest_start - 1
            if next_end >= cursor_end:
                raise BybitAPIError("kline pagination made no progress")
            cursor_end = next_end

        candles = sorted(by_start.values(), key=lambda candle: candle.start_ms)
        validate_candles(candles, expected_interval_ms=interval_ms)
        return candles

    @staticmethod
    def _parse_rest_candle(
        row: Any,
        *,
        symbol: str,
        interval: str,
        interval_ms: int,
        server_time_ms: int,
    ) -> Candle:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) < 7:
            raise BybitAPIError("invalid kline row")
        try:
            start_ms = int(row[0])
        except (TypeError, ValueError) as exc:
            raise DataValidationError("invalid candle start time") from exc
        end_ms = start_ms + interval_ms - 1
        return Candle(
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            end_ms=end_ms,
            open=_decimal(row[1], "open"),
            high=_decimal(row[2], "high"),
            low=_decimal(row[3], "low"),
            close=_decimal(row[4], "close"),
            volume=_decimal(row[5], "volume"),
            turnover=_decimal(row[6], "turnover"),
            confirmed=end_ms < server_time_ms,
        )


class BybitWebSocketParser:
    """Turns public V5 messages into closed candles and merged ticker snapshots."""

    def __init__(self) -> None:
        self._ticker_state: dict[str, dict[str, Any]] = {}

    def parse_candles(self, message: Mapping[str, Any]) -> list[Candle]:
        topic = str(message.get("topic", ""))
        parts = topic.split(".")
        if len(parts) != 3 or parts[0] != "kline":
            return []
        interval, symbol = parts[1], parts[2]
        interval_ms = interval_to_milliseconds(interval)
        data = message.get("data", [])
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            raise DataValidationError("invalid WebSocket kline data")
        candles: list[Candle] = []
        for item in data:
            if not isinstance(item, Mapping) or item.get("confirm") is not True:
                continue
            try:
                start_ms = int(item["start"])
                end_ms = int(item["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DataValidationError("invalid WebSocket candle timestamp") from exc
            candle = Candle(
                symbol=symbol,
                interval=interval,
                start_ms=start_ms,
                end_ms=end_ms,
                open=_decimal(item.get("open"), "open"),
                high=_decimal(item.get("high"), "high"),
                low=_decimal(item.get("low"), "low"),
                close=_decimal(item.get("close"), "close"),
                volume=_decimal(item.get("volume"), "volume"),
                turnover=_decimal(item.get("turnover"), "turnover"),
                confirmed=True,
            )
            validate_candles([candle], expected_interval_ms=interval_ms)
            candles.append(candle)
        return candles

    def parse_ticker(self, message: Mapping[str, Any]) -> MarketSnapshot | None:
        topic = str(message.get("topic", ""))
        if not topic.startswith("tickers."):
            return None
        symbol = topic.removeprefix("tickers.")
        data = message.get("data")
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            item = data[0] if data else None
        else:
            item = data
        if not isinstance(item, Mapping):
            raise DataValidationError("invalid WebSocket ticker data")

        state = self._ticker_state.setdefault(symbol, {})
        if message.get("type") == "snapshot":
            state.clear()
        state.update(item)
        funding = state.get("fundingRate")
        open_interest = state.get("openInterest")
        if funding is None and open_interest is None:
            return None
        try:
            timestamp_ms = int(message["ts"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DataValidationError("invalid ticker timestamp") from exc
        return MarketSnapshot(
            symbol=symbol,
            timestamp_ms=timestamp_ms,
            funding_rate=None if funding is None else _decimal(funding, "fundingRate"),
            open_interest=(
                None if open_interest is None else _decimal(open_interest, "openInterest")
            ),
        )


class WebSocketAdapter(Protocol):
    def kline_stream(self, *, interval: str, symbol: str, callback: Callable[..., Any]) -> Any: ...

    def ticker_stream(self, *, symbol: str, callback: Callable[..., Any]) -> Any: ...


class BybitWebSocketCollector:
    """Registers raw pybit-compatible streams and emits validated records."""

    def __init__(
        self,
        socket: WebSocketAdapter,
        parser: BybitWebSocketParser | None = None,
    ) -> None:
        self.socket = socket
        self.parser = parser or BybitWebSocketParser()

    def subscribe(
        self,
        *,
        symbol: str,
        interval: str | int,
        on_candle: Callable[[Candle], None],
        on_snapshot: Callable[[MarketSnapshot], None],
    ) -> None:
        normalized_symbol = symbol.upper()
        normalized_interval = str(interval)
        interval_to_milliseconds(normalized_interval)

        def handle_kline(message: Mapping[str, Any]) -> None:
            for candle in self.parser.parse_candles(message):
                on_candle(candle)

        def handle_ticker(message: Mapping[str, Any]) -> None:
            snapshot = self.parser.parse_ticker(message)
            if snapshot is not None:
                on_snapshot(snapshot)

        self.socket.kline_stream(
            interval=normalized_interval,
            symbol=normalized_symbol,
            callback=handle_kline,
        )
        self.socket.ticker_stream(symbol=normalized_symbol, callback=handle_ticker)
