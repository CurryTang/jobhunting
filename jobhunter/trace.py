from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TrajectoryLogger:
    """Append structured search-trajectory events to a JSONL file.

    Each line is one event: {"ts": ..., "event": ..., **payload}.
    A null path makes every call a no-op so callers never need branches.
    """

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path).expanduser() if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **payload: Any) -> None:
        if self.path is None:
            return
        record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


NULL_TRACER = TrajectoryLogger(None)
