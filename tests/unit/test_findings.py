# tests/unit/test_findings.py
from __future__ import annotations
import json
from pathlib import Path
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.types import InboxFinding


def _finding(mid="m1", prio="P1"):
    return InboxFinding(ts="2026-06-02T10:00:00+00:00", vendor="vercel", priority=prio,
                        rule_id="build_failure", subject="Deploy failed", summary="vercel: Deploy failed",
                        message_id=mid, link="https://app.agentmail.to/x", hash="abc",
                        dedup_decision="digest_only")


def test_writes_dated_jsonl(tmp_path: Path):
    w = InboxFindingsWriter(tmp_path, run_date="2026-06-02")
    w.write_finding(_finding())
    line = (tmp_path / "2026-06-02.jsonl").read_text().strip()
    obj = json.loads(line)
    assert obj["priority"] == "P1"
    assert obj["message_id"] == "m1"
    assert obj["repo"] is None


def test_read_day_returns_findings(tmp_path: Path):
    w = InboxFindingsWriter(tmp_path, run_date="2026-06-02")
    w.write_finding(_finding("m1", "P1"))
    w.write_finding(_finding("m2", "P3"))
    got = InboxFindingsWriter.read_day(tmp_path, "2026-06-02")
    assert {g["message_id"] for g in got} == {"m1", "m2"}


def test_read_day_empty_when_missing(tmp_path: Path):
    assert InboxFindingsWriter.read_day(tmp_path, "2026-06-01") == []
