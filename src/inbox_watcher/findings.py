"""Rich JSONL writer/reader for inbox findings."""
from __future__ import annotations
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any
from inbox_watcher.types import InboxFinding


class InboxFindingsWriter:
    def __init__(self, root: Path, run_date: str) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._dated = root / f"{run_date}.jsonl"
        self._runs = root / "runs.jsonl"
        self._errors = root / "errors.jsonl"

    def write_finding(self, f: InboxFinding) -> None:
        self._append(self._dated, asdict(f))

    def write_run_summary(self, summary: dict[str, Any]) -> None:
        self._append(self._runs, summary)

    def write_error(self, error: dict[str, Any]) -> None:
        self._append(self._errors, error)

    @staticmethod
    def read_day(root: Path, run_date: str) -> list[dict[str, Any]]:
        path = root / f"{run_date}.jsonl"
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logging.getLogger("inbox_watcher.findings").warning(
                    "skipping malformed JSONL line in %s", path)
        return out

    @staticmethod
    def _append(path: Path, obj: dict[str, Any]) -> None:
        # Single-writer assumption: no file locking. Overlapping runs against the same
        # path could interleave partial lines; read_day tolerates that by skipping bad lines.
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, separators=(",", ":")) + "\n")
