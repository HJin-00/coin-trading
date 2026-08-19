from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


class TradingHalted(RuntimeError):
    pass


class KillSwitch:
    """A file-backed latch that stays engaged across process restarts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def engaged(self) -> bool:
        return self.path.exists()

    def engage(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("kill-switch reason is required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"engaged_at": datetime.now(UTC).isoformat(), "reason": reason}
        self.path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def ensure_trading_allowed(self) -> None:
        if self.engaged:
            raise TradingHalted(f"kill switch is engaged: {self.path}")

    def reset(self, *, acknowledgement: str) -> None:
        if acknowledgement != "I_ACCEPT_THE_RISK":
            raise ValueError("explicit risk acknowledgement is required")
        self.path.unlink(missing_ok=True)
