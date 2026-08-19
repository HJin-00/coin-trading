from __future__ import annotations

from dataclasses import dataclass

from coin_trading.domain import Side
from coin_trading.multimodal.reviewer import ReviewDecision


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    data_end_ms: int
    expected_side: Side
    baseline_side: Side
    review: ReviewDecision


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    cases: int
    baseline_accuracy: float
    review_accuracy: float
    incremental_accuracy: float


def evaluate_cases(cases: list[EvaluationCase]) -> EvaluationResult:
    if not cases:
        raise ValueError("evaluation cases cannot be empty")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("evaluation case ids must be unique")
    baseline_correct = sum(case.baseline_side is case.expected_side for case in cases)
    review_correct = sum(case.review.side is case.expected_side for case in cases)
    count = len(cases)
    baseline_accuracy = baseline_correct / count
    review_accuracy = review_correct / count
    return EvaluationResult(
        cases=count,
        baseline_accuracy=baseline_accuracy,
        review_accuracy=review_accuracy,
        incremental_accuracy=review_accuracy - baseline_accuracy,
    )
