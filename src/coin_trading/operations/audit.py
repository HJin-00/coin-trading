from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, event: str, **fields: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
