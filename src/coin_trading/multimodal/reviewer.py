from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from coin_trading.domain import Side

PROMPT_VERSION = "multimodal-review-v1"
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "side": {"type": "string", "enum": ["LONG", "SHORT", "NO_TRADE"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "invalidation_price": {"type": ["number", "null"]},
        "reason_codes": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
        },
    },
    "required": ["side", "confidence", "invalidation_price", "reason_codes"],
    "additionalProperties": False,
}


class ResponsesAPI(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class OpenAIClient(Protocol):
    responses: ResponsesAPI


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    side: Side
    confidence: float
    invalidation_price: float | None
    reason_codes: tuple[str, ...]
    model: str
    prompt_version: str = PROMPT_VERSION

    @classmethod
    def no_trade(cls, *, model: str, reason: str) -> ReviewDecision:
        return cls(Side.NO_TRADE, 0.0, None, (reason,), model)


class MultimodalReviewer:
    def __init__(self, client: OpenAIClient, *, model: str, max_output_tokens: int = 160) -> None:
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens

    def review(self, *, chart_path: str | Path, numeric_context: dict[str, Any]) -> ReviewDecision:
        try:
            image = base64.b64encode(Path(chart_path).read_bytes()).decode("ascii")
            response = self.client.responses.create(
                model=self.model,
                store=False,
                timeout=20.0,
                max_output_tokens=self.max_output_tokens,
                instructions=(
                    "Review the supplied closed-candle chart and numeric indicators. "
                    "Return a conservative corroborating signal only. "
                    "Use NO_TRADE when signals conflict."
                ),
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps(numeric_context, separators=(",", ":")),
                            },
                            {
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{image}",
                                "detail": "low",
                            },
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "trade_review",
                        "strict": True,
                        "schema": RESPONSE_SCHEMA,
                    }
                },
            )
            payload = json.loads(response.output_text)
            return self._parse(payload)
        except Exception:
            return ReviewDecision.no_trade(model=self.model, reason="review_failure")

    def _parse(self, payload: Any) -> ReviewDecision:
        if not isinstance(payload, dict):
            raise ValueError("review is not an object")
        side = Side(payload["side"])
        confidence = float(payload["confidence"])
        invalidation = payload["invalidation_price"]
        reasons = payload["reason_codes"]
        if not 0 <= confidence <= 1 or not isinstance(reasons, list):
            raise ValueError("invalid review fields")
        if invalidation is not None and float(invalidation) <= 0:
            raise ValueError("invalidation price must be positive")
        return ReviewDecision(
            side=side,
            confidence=confidence,
            invalidation_price=None if invalidation is None else float(invalidation),
            reason_codes=tuple(str(reason) for reason in reasons[:4]),
            model=self.model,
        )
