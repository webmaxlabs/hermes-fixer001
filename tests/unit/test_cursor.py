# tests/unit/test_cursor.py
from __future__ import annotations
from pathlib import Path
from inbox_watcher.cursor import Cursor


def test_read_default_when_missing(tmp_path: Path):
    c = Cursor(tmp_path / "cursor.json")
    assert c.last_ts() == ""


def test_write_then_read(tmp_path: Path):
    p = tmp_path / "cursor.json"
    c = Cursor(p)
    c.set("2026-06-02T10:00:00+00:00")
    assert Cursor(p).last_ts() == "2026-06-02T10:00:00+00:00"


def test_set_only_advances(tmp_path: Path):
    c = Cursor(tmp_path / "cursor.json")
    c.set("2026-06-02T10:00:00+00:00")
    c.set("2026-06-02T09:00:00+00:00")  # older, ignored
    assert c.last_ts() == "2026-06-02T10:00:00+00:00"
