from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from coin_trading.market_data import (
    BybitRestClient,
    BybitWebSocketParser,
    Candle,
    DataValidationError,
    ImmutableJsonlStore,
    validate_candles,
)


def row(start: int, price: str = "100") -> list[str]:
    return [str(start), price, "110", "90", "105", "2", "205"]


class FakeTransport:
    def __init__(self) -> None:
        self.ends: list[int] = []

    def get(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        if path.endswith("time"):
            return {"retCode": 0, "result": {"timeNano": "1000000000000000000"}}
        end = int(params["end"])
        self.ends.append(end)
        if end >= 180_000:
            rows = [row(180_000), row(120_000)]
        else:
            rows = [row(60_000), row(0)]
        return {"retCode": 0, "result": {"list": rows}}


def test_rest_client_paginates_deduplicates_and_sorts() -> None:
    transport = FakeTransport()
    client = BybitRestClient(transport=transport)

    candles = client.fetch_candles(
        symbol="btcusdt", interval="1", start_ms=0, end_ms=240_000, page_size=2
    )

    assert [candle.start_ms for candle in candles] == [0, 60_000, 120_000, 180_000]
    assert transport.ends == [239_999, 119_999]
    assert all(candle.confirmed for candle in candles)


def test_rest_client_excludes_current_unconfirmed_candle() -> None:
    class CurrentTransport(FakeTransport):
        def get(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
            if path.endswith("time"):
                return {"retCode": 0, "result": {"timeNano": "150000000000"}}
            return {"retCode": 0, "result": {"list": [row(120_000), row(60_000)]}}

    candles = BybitRestClient(transport=CurrentTransport()).fetch_candles(
        symbol="BTCUSDT", interval=1, start_ms=60_000, end_ms=180_000
    )
    assert [candle.start_ms for candle in candles] == [60_000]


def test_websocket_ignores_open_candle_and_parses_closed_candle() -> None:
    parser = BybitWebSocketParser()
    base = {
        "start": 0,
        "end": 59_999,
        "open": "100",
        "high": "110",
        "low": "90",
        "close": "105",
        "volume": "2",
        "turnover": "205",
    }
    assert parser.parse_candles({"topic": "kline.1.BTCUSDT", "data": [{**base}]}) == []
    candles = parser.parse_candles(
        {"topic": "kline.1.BTCUSDT", "data": [{**base, "confirm": True}]}
    )
    assert len(candles) == 1
    assert candles[0].confirmed


def test_ticker_delta_preserves_unchanged_fields() -> None:
    parser = BybitWebSocketParser()
    first = parser.parse_ticker(
        {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "ts": 1,
            "data": {"fundingRate": "0.0001", "openInterest": "12.5"},
        }
    )
    second = parser.parse_ticker(
        {
            "topic": "tickers.BTCUSDT",
            "type": "delta",
            "ts": 2,
            "data": {"openInterest": "13"},
        }
    )
    assert first is not None and first.funding_rate == Decimal("0.0001")
    assert second is not None and second.funding_rate == Decimal("0.0001")
    assert second.open_interest == Decimal("13")


def test_validation_rejects_gaps() -> None:
    candles = [
        Candle("BTCUSDT", "1", start, start + 59_999, *map(Decimal, values), True)
        for start, values in [
            (0, ("100", "110", "90", "105", "2", "205")),
            (120_000, ("105", "115", "100", "110", "3", "325")),
        ]
    ]
    with pytest.raises(DataValidationError, match="missing candle"):
        validate_candles(candles, expected_interval_ms=60_000)


def test_immutable_store_uses_exclusive_creation(tmp_path: Path) -> None:
    store = ImmutableJsonlStore(tmp_path)
    collected_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    candle = Candle(
        "BTCUSDT",
        "1",
        0,
        59_999,
        Decimal("100"),
        Decimal("110"),
        Decimal("90"),
        Decimal("105"),
        Decimal("2"),
        Decimal("205"),
        True,
    )
    path = store.write_batch(
        dataset="candles", symbol="BTCUSDT", records=[candle], collected_at=collected_at
    )
    assert json.loads(path.read_text())["close"] == "105"
    with pytest.raises(FileExistsError):
        store.write_batch(
            dataset="candles", symbol="BTCUSDT", records=[candle], collected_at=collected_at
        )
