from __future__ import annotations

from coin_trading.config import Settings
from coin_trading.domain import AccountState, RiskDecision, Side, TradeProposal


class RiskEngine:
    """Deterministic guardrail that cannot be overridden by an LLM signal."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, proposal: TradeProposal, account: AccountState) -> RiskDecision:
        if proposal.side is Side.NO_TRADE:
            return RiskDecision(False, "strategy selected NO_TRADE")
        if account.equity <= 0:
            return RiskDecision(False, "account equity must be positive")
        if proposal.stop_price is None:
            return RiskDecision(False, "a protective stop is required")
        if proposal.entry_price <= 0 or proposal.stop_price <= 0:
            return RiskDecision(False, "prices must be positive")
        if proposal.leverage <= 0 or proposal.leverage > self.settings.max_leverage:
            return RiskDecision(False, "leverage exceeds configured limit")
        if account.open_positions >= self.settings.max_open_positions:
            return RiskDecision(False, "maximum open positions reached")
        if account.daily_pnl <= -(account.equity * self.settings.daily_loss_limit):
            return RiskDecision(False, "daily loss limit reached")
        if proposal.side is Side.LONG and proposal.stop_price >= proposal.entry_price:
            return RiskDecision(False, "long stop must be below entry")
        if proposal.side is Side.SHORT and proposal.stop_price <= proposal.entry_price:
            return RiskDecision(False, "short stop must be above entry")

        stop_distance = abs(proposal.entry_price - proposal.stop_price)
        risk_budget = account.equity * self.settings.risk_per_trade
        risk_quantity = risk_budget / stop_distance
        notional_cap = account.equity * self.settings.max_position_fraction
        capped_quantity = notional_cap / proposal.entry_price
        quantity = min(risk_quantity, capped_quantity)
        notional = quantity * proposal.entry_price

        if quantity <= 0:
            return RiskDecision(False, "calculated quantity is not positive")
        return RiskDecision(True, "approved", quantity=quantity, notional=notional)
