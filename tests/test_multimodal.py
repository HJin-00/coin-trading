from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from coin_trading.domain import Side
from coin_trading.multimodal import (
    EvaluationCase,
    MultimodalReviewer,
    ReviewDecision,
    build_numeric_context,
    consensus_gate,
    evaluate_cases,
    render_canonical_chart,
)
from coin_trading.strategy import IndicatorSnapshot, MarketRegime, RegimeAssessment, Signal


def indicators() -> IndicatorSnapshot:
    return IndicatorSnapshot(
        1,
        100,
        101,
        99,
        50,
        1,
        0.5,
        100,
        105,
        95,
        2,
        10,
        1.2,
    )


def signal(side: Side = Side.LONG) -> Signal:
    regime = RegimeAssessment(MarketRegime.TREND, 0.02, 0.02, 0.1)
    return Signal(side, "test", indicators(), regime)


class FakeResponses:
    def __init__(self, output: dict[str, Any] | None = None, *, fails: bool = False) -> None:
        self.output = output
        self.fails = fails
        self.request: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.request = kwargs
        if self.fails:
            raise TimeoutError
        return SimpleNamespace(output_text=json.dumps(self.output))


def test_reviewer_uses_compact_structured_request(tmp_path: Path) -> None:
    responses = FakeResponses(
        {
            "side": "LONG",
            "confidence": 0.8,
            "invalidation_price": 98,
            "reason_codes": ["trend_aligned"],
        }
    )
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    reviewer = MultimodalReviewer(SimpleNamespace(responses=responses), model="test-model")
    decision = reviewer.review(chart_path=chart, numeric_context={"rsi": 50})
    assert decision.side is Side.LONG
    assert responses.request is not None
    assert responses.request["store"] is False
    assert responses.request["timeout"] == 20.0
    assert responses.request["max_output_tokens"] == 160
    assert responses.request["text"]["format"]["type"] == "json_schema"


def test_reviewer_fails_closed_on_api_error(tmp_path: Path) -> None:
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    reviewer = MultimodalReviewer(
        SimpleNamespace(responses=FakeResponses(fails=True)), model="test-model"
    )
    decision = reviewer.review(chart_path=chart, numeric_context={})
    assert decision.side is Side.NO_TRADE
    assert decision.reason_codes == ("review_failure",)


def test_consensus_cannot_override_strategy_or_invalid_stop() -> None:
    review = ReviewDecision(Side.LONG, 0.9, 98, ("aligned",), "test-model")
    assert consensus_gate(signal(Side.NO_TRADE), review).side is Side.NO_TRADE
    invalid = ReviewDecision(Side.LONG, 0.9, 101, ("aligned",), "test-model")
    assert not consensus_gate(signal(), invalid).approved
    assert consensus_gate(signal(), review).approved


def test_context_excludes_raw_candles() -> None:
    regime = RegimeAssessment(MarketRegime.TREND, 0.02, 0.02, 0.1)
    context = build_numeric_context(
        symbol="BTCUSDT", interval="60", indicators=indicators(), regime=regime
    )
    assert "candles" not in context
    assert context["rsi"] == 50


def test_evaluation_reports_increment_over_baseline() -> None:
    review = ReviewDecision(Side.LONG, 0.9, 98, ("aligned",), "test-model")
    result = evaluate_cases([EvaluationCase("case-1", 1, Side.LONG, Side.NO_TRADE, review)])
    assert result.incremental_accuracy == 1


def test_chart_rejects_short_history_without_loading_matplotlib(tmp_path: Path) -> None:
    try:
        render_canonical_chart([], tmp_path / "chart.png")
    except ValueError as exc:
        assert "120" in str(exc)
    else:
        raise AssertionError("short chart history must be rejected")
