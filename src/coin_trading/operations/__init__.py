"""Local paper operations, audit logging, reporting, and kill switches."""

from coin_trading.operations.audit import AuditLogger
from coin_trading.operations.paper import PaperBroker, PaperPosition, PaperTrade
from coin_trading.operations.reporting import DailyReport, build_daily_report
from coin_trading.operations.runner import PaperTradingRunner
from coin_trading.operations.safety import KillSwitch, TradingHalted
from coin_trading.operations.state import PaperStateStore

__all__ = [
    "AuditLogger",
    "DailyReport",
    "KillSwitch",
    "PaperBroker",
    "PaperPosition",
    "PaperStateStore",
    "PaperTrade",
    "PaperTradingRunner",
    "TradingHalted",
    "build_daily_report",
]
