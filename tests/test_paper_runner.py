from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from test_config import safe_settings
from test_strategy import fixed_signal

from coin_trading.domain import Side
from coin_trading.market_data import Candle
from coin_trading.operations import AuditLogger, KillSwitch, PaperBroker, PaperStateStore
from coin_trading.operations.cli import build_parser
from coin_trading.operations.runner import PaperTradingRunner
from coin_trading.risk import RiskEngine
from coin_trading.strategy import Signal


def candle(index: int) -> Candle:
    return Candle(
        "BTCUSDT",
        "1",
        index * 60_000,
        (index + 1) * 60_000 - 1,
        Decimal("100"),
        Decimal("101"),
        Decimal("99"),
        Decimal("100"),
        Decimal("10"),
        Decimal("1000"),
        True,
    )


class AlwaysLong:
    minimum_history = 1

    def evaluate(self, candles: list[Candle]) -> Signal:
        return fixed_signal(Side.LONG, candles[-1].end_ms)


def dependencies(tmp_path: Path) -> tuple[PaperBroker, PaperStateStore]:
    broker = PaperBroker(
        initial_equity=Decimal("10000"),
        kill_switch=KillSwitch(tmp_path / "HALT"),
        audit=AuditLogger(tmp_path / "audit.jsonl"),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    return broker, PaperStateStore(tmp_path / "state.json")


def test_runner_enters_signal_on_next_candle_and_ignores_duplicate(tmp_path: Path) -> None:
    broker, state = dependencies(tmp_path)
    runner = PaperTradingRunner(
        broker=broker,
        strategy=AlwaysLong(),
        risk_engine=RiskEngine(safe_settings()),
        state_store=state,
        history=[candle(0)],
    )
    runner.on_candle(candle(1))
    assert broker.position is None
    runner.on_candle(candle(2))
    assert broker.position is not None
    assert broker.position.entry_time_ms == candle(2).start_ms
    runner.on_candle(candle(2))
    assert len([line for line in (tmp_path / "audit.jsonl").read_text().splitlines()]) == 3


def test_paper_state_round_trip_restores_open_position(tmp_path: Path) -> None:
    broker, state = dependencies(tmp_path)
    runner = PaperTradingRunner(
        broker=broker,
        strategy=AlwaysLong(),
        risk_engine=RiskEngine(safe_settings()),
        state_store=state,
        history=[candle(0)],
    )
    runner.on_candle(candle(1))
    runner.on_candle(candle(2))
    payload = state.load()
    assert payload is not None

    restored, _ = dependencies(tmp_path / "restored")
    restored.restore_state(payload["broker"])
    assert restored.position is not None
    assert restored.position.quantity == broker.position.quantity
    assert restored.equity == broker.equity


def test_paper_cli_defaults_are_safe() -> None:
    args = build_parser().parse_args([])
    assert args.initial_equity == Decimal("10000")
    assert args.history_candles >= 60
