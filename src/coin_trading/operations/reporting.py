from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from coin_trading.operations.paper import PaperTrade


@dataclass(frozen=True, slots=True)
class DailyReport:
    trades: int
    wins: int
    losses: int
    win_rate: float
    average_win_loss_ratio: float
    max_drawdown: float
    net_pnl: Decimal
    cumulative_return: float


def build_daily_report(
    trades: list[PaperTrade], *, initial_equity: Decimal, current_equity: Decimal
) -> DailyReport:
    wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [-trade.net_pnl for trade in trades if trade.net_pnl < 0]
    ratio = 0.0
    if wins and losses:
        ratio = float((sum(wins) / len(wins)) / (sum(losses) / len(losses)))
    equity = initial_equity
    peak = initial_equity
    max_drawdown = Decimal("0")
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return DailyReport(
        trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=0.0 if not trades else len(wins) / len(trades),
        average_win_loss_ratio=ratio,
        max_drawdown=float(max_drawdown),
        net_pnl=sum((trade.net_pnl for trade in trades), Decimal("0")),
        cumulative_return=float(current_equity / initial_equity - 1),
    )
