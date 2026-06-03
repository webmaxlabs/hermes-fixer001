"""Persistent last-seen-timestamp cursor (JSON state file)."""
from __future__ import annotations
import json
from pathlib import Path


class Cursor:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def last_ts(self) -> str:
        if not self._path.exists():
            return ""
        try:
            return str(json.loads(self._path.read_text()).get("last_ts", ""))
        except (json.JSONDecodeError, OSError):
            return ""

    def set(self, ts: str) -> None:
        # Monotonic: never move the cursor backwards.
        if ts and ts <= self.last_ts():
            return
        self._path.write_text(json.dumps({"last_ts": ts}))
