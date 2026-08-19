from __future__ import annotations

import argparse
import signal
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from coin_trading.config import Settings
from coin_trading.market_data import BybitRestClient, BybitWebSocketCollector, Candle
from coin_trading.market_data.bybit import interval_to_milliseconds
from coin_trading.operations.audit import AuditLogger
from coin_trading.operations.paper import PaperBroker
from coin_trading.operations.reporting import build_daily_report
from coin_trading.operations.runner import PaperTradingRunner
from coin_trading.operations.safety import KillSwitch
from coin_trading.operations.state import PaperStateStore
from coin_trading.risk import RiskEngine
from coin_trading.strategy.signals import BaselineStrategy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run local paper trading from Bybit mainnet public closed candles"
    )
    parser.add_argument("--initial-equity", type=Decimal, default=Decimal("10000"))
    parser.add_argument("--state-dir", type=Path, default=Path("data/paper"))
    parser.add_argument("--history-candles", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.history_candles < BaselineStrategy.minimum_history:
        raise SystemExit("--history-candles is below strategy minimum history")
    settings = Settings.from_env()
    interval = str(settings.interval_minutes)
    interval_ms = interval_to_milliseconds(interval)
    state_store = PaperStateStore(args.state_dir / "state.json")
    audit = AuditLogger(args.state_dir / "audit.jsonl")
    broker = PaperBroker(
        initial_equity=args.initial_equity,
        kill_switch=KillSwitch(args.state_dir / "HALT"),
        audit=audit,
        daily_loss_limit=settings.daily_loss_limit,
    )
    saved = state_store.load()
    saved_last = -1
    if saved is not None:
        broker.restore_state(saved["broker"])
        saved_last = int(saved.get("last_processed_ms", -1))

    now_ms = int(datetime.now(UTC).timestamp() * 1_000)
    history = BybitRestClient(testnet=False).fetch_candles(
        symbol=settings.symbol,
        interval=interval,
        start_ms=now_ms - (args.history_candles + 2) * interval_ms,
        end_ms=now_ms,
    )
    seed = (
        history
        if saved is None
        else [candle for candle in history if candle.start_ms <= saved_last]
    )
    runner = PaperTradingRunner(
        broker=broker,
        strategy=BaselineStrategy(),
        risk_engine=RiskEngine(settings),
        state_store=state_store,
        history=seed,
    )
    if saved is not None:
        runner.last_processed_ms = saved_last
        for missed in (candle for candle in history if candle.start_ms > saved_last):
            runner.on_candle(missed)

    try:
        from pybit.unified_trading import WebSocket
    except ImportError as exc:
        raise SystemExit("install the Bybit extra: pip install -e '.[bybit]'") from exc

    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    socket = WebSocket(testnet=False, channel_type="linear")
    collector = BybitWebSocketCollector(socket)

    def handle_candle(candle: Candle) -> None:
        try:
            runner.on_candle(candle)
        except Exception as exc:
            broker.kill_switch.engage("paper runner callback failed")
            audit.record("paper_runner_failed", error_type=type(exc).__name__)
            stopped.set()

    collector.subscribe(
        symbol=settings.symbol,
        interval=interval,
        on_candle=handle_candle,
        on_snapshot=lambda _snapshot: None,
    )
    audit.record("paper_runner_started", symbol=settings.symbol, interval=interval)
    stopped.wait()
    report = build_daily_report(
        broker.trades,
        initial_equity=broker.initial_equity,
        current_equity=broker.equity,
    )
    audit.record(
        "paper_runner_stopped",
        equity=str(broker.equity),
        trades=report.trades,
        cumulative_return=report.cumulative_return,
        max_drawdown=report.max_drawdown,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
