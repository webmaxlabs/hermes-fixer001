"""Append-only dispatch ledger keyed by error_signature, folded latest-row-wins.

Findings stay immutable; dispatch state lives here. In dry-run (Phase A) rows are
always written open=true and never closed, so a signature dispatches once. Phase B
appends open=false rows when the corresponding PR closes to re-enable dispatch.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("inbox_watcher.ledger")


class DispatchLedger:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    def _rows(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("skipping malformed ledger line in %s", self._path)
        return out

    def fold(self) -> dict[str, dict[str, Any]]:
        """Latest row per error_signature wins (rows are appended in time order)."""
        folded: dict[str, dict[str, Any]] = {}
        for row in self._rows():
            sig = row.get("error_signature")
            if sig:
                folded[sig] = row
        return folded

    def open_signatures(self) -> set[str]:
        return {sig for sig, row in self.fold().items() if row.get("open")}

    def record(self, *, error_signature: str, repo: str, rule_id: str,
               priority: str, mode: str, now: str) -> None:
        existing = self.fold().get(error_signature)
        if existing:
            first_ts = existing.get("first_dispatched_ts", now)
            seen = int(existing.get("seen_count", 1)) + 1
            is_open = bool(existing.get("open", True))
        else:
            first_ts, seen, is_open = now, 1, True
        self._append({
            "error_signature": error_signature, "repo": repo, "rule_id": rule_id,
            "priority": priority, "first_dispatched_ts": first_ts, "last_seen_ts": now,
            "seen_count": seen, "mode": mode, "open": is_open,
        })
