from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_execution import FakeClient

from coin_trading.domain import Side
from coin_trading.execution import (
    BybitDemoExecutor,
    BybitExecutionError,
    ExecutionEnvironment,
    OrderIntent,
)
from coin_trading.market_data import Candle
from coin_trading.operations import (
    AuditLogger,
    KillSwitch,
    PaperBroker,
    TradingHalted,
    build_daily_report,
)


def intent(*, quantity: str = "1") -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSDT",
        side=Side.LONG,
        quantity=Decimal(quantity),
        expected_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        take_profit_price=Decimal("110"),
        idempotency_key="paper-1",
    )


def candle(*, low: str, high: str, close: str = "100") -> Candle:
    return Candle(
        "BTCUSDT",
        "1",
        0,
        59_999,
        Decimal("100"),
        Decimal(high),
        Decimal(low),
        Decimal(close),
        Decimal("10"),
        Decimal("1000"),
        True,
    )


def broker(tmp_path: Path, **kwargs: object) -> PaperBroker:
    return PaperBroker(
        initial_equity=Decimal("10000"),
        kill_switch=KillSwitch(tmp_path / "HALT"),
        audit=AuditLogger(tmp_path / "audit.jsonl"),
        **kwargs,
    )


def test_execution_environments_are_explicit() -> None:
    assert ExecutionEnvironment.TESTNET.value == "TESTNET"
    assert ExecutionEnvironment.DEMO.value == "DEMO"
    assert ExecutionEnvironment.LOCAL_PAPER.value == "LOCAL_PAPER"


def test_demo_adapter_restricts_leverage_and_skips_unsupported_call() -> None:
    client = FakeClient()
    demo = BybitDemoExecutor(client)
    demo.recover()
    with pytest.raises(BybitExecutionError, match="1x"):
        demo.submit(replace(intent(), leverage=Decimal("2")))
    demo.submit(intent())
    assert not client.leverage


def test_paper_broker_uses_mainnet_candle_and_conservative_stop(tmp_path: Path) -> None:
    paper = broker(tmp_path, fee_rate=Decimal("0"), slippage_bps=Decimal("0"))
    paper.submit(intent(), market_price=Decimal("100"), timestamp_ms=0)
    trade = paper.on_candle(candle(low="94", high="111"))
    assert trade is not None
    assert trade.exit_reason == "stop"
    assert trade.exit_price == Decimal("95")
    assert trade.net_pnl == Decimal("-5")


def test_paper_broker_rejects_unconfirmed_candle(tmp_path: Path) -> None:
    paper = broker(tmp_path)
    invalid = candle(low="99", high="101")
    invalid = replace(invalid, confirmed=False)
    with pytest.raises(ValueError, match="confirmed"):
        paper.on_candle(invalid)


def test_daily_loss_engages_persistent_kill_switch(tmp_path: Path) -> None:
    switch = KillSwitch(tmp_path / "HALT")
    paper = PaperBroker(
        initial_equity=Decimal("10000"),
        kill_switch=switch,
        audit=AuditLogger(tmp_path / "audit.jsonl"),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    paper.submit(intent(quantity="100"), market_price=Decimal("100"), timestamp_ms=0)
    paper.on_candle(candle(low="94", high="101"))
    assert switch.engaged
    with pytest.raises(TradingHalted):
        paper.submit(intent(), market_price=Decimal("100"), timestamp_ms=1)


def test_kill_switch_reset_requires_explicit_acknowledgement(tmp_path: Path) -> None:
    switch = KillSwitch(tmp_path / "HALT")
    switch.engage("manual halt")
    with pytest.raises(ValueError, match="acknowledgement"):
        switch.reset(acknowledgement="yes")
    switch.reset(acknowledgement="I_ACCEPT_THE_RISK")
    assert not switch.engaged


def test_audit_log_and_daily_report(tmp_path: Path) -> None:
    paper = broker(tmp_path, fee_rate=Decimal("0"), slippage_bps=Decimal("0"))
    paper.submit(intent(), market_price=Decimal("100"), timestamp_ms=0)
    trade = paper.on_candle(candle(low="99", high="111", close="110"))
    assert trade is not None
    report = build_daily_report(
        paper.trades, initial_equity=paper.initial_equity, current_equity=paper.equity
    )
    assert report.trades == 1
    assert report.wins == 1
    assert report.max_drawdown == 0
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["paper_position_opened", "paper_position_closed"]
