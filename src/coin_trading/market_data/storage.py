from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class SerializableRecord(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


class ImmutableJsonlStore:
    """Append-free raw storage: every batch is created once with exclusive mode."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write_batch(
        self,
        *,
        dataset: str,
        symbol: str,
        records: Iterable[SerializableRecord | Mapping[str, Any]],
        collected_at: datetime | None = None,
    ) -> Path:
        if not dataset.replace("_", "").isalnum() or not symbol.isalnum():
            raise ValueError("dataset and symbol must be path-safe alphanumeric names")
        materialized = list(records)
        if not materialized:
            raise ValueError("cannot store an empty batch")
        lines = []
        for record in materialized:
            payload = record if isinstance(record, Mapping) else record.to_dict()
            lines.append(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        timestamp = (collected_at or datetime.now(UTC)).astimezone(UTC)
        filename = timestamp.strftime("%Y%m%dT%H%M%S.%fZ.jsonl")
        directory = self.root / dataset / symbol.upper()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        with path.open("x", encoding="utf-8", newline="\n") as output:
            for line in lines:
                output.write(line)
                output.write("\n")
            output.flush()
        return path
