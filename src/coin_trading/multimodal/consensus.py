from __future__ import annotations

from dataclasses import dataclass

from coin_trading.domain import Side
from coin_trading.multimodal.reviewer import ReviewDecision
from coin_trading.strategy.signals import Signal


@dataclass(frozen=True, slots=True)
class ConsensusDecision:
    approved: bool
    side: Side
    reason: str


def consensus_gate(
    strategy: Signal,
    review: ReviewDecision,
    *,
    minimum_confidence: float = 0.65,
) -> ConsensusDecision:
    if strategy.side is Side.NO_TRADE:
        return ConsensusDecision(False, Side.NO_TRADE, "strategy_no_trade")
    if review.side is not strategy.side:
        return ConsensusDecision(False, Side.NO_TRADE, "review_disagrees")
    if review.confidence < minimum_confidence:
        return ConsensusDecision(False, Side.NO_TRADE, "review_confidence_too_low")
    invalidation = review.invalidation_price
    if invalidation is None:
        return ConsensusDecision(False, Side.NO_TRADE, "review_has_no_invalidation")
    entry = strategy.indicators.close
    if strategy.side is Side.LONG and invalidation >= entry:
        return ConsensusDecision(False, Side.NO_TRADE, "invalid_long_invalidation")
    if strategy.side is Side.SHORT and invalidation <= entry:
        return ConsensusDecision(False, Side.NO_TRADE, "invalid_short_invalidation")
    return ConsensusDecision(True, strategy.side, "consensus")
