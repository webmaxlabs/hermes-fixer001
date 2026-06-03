# tests/unit/test_runner.py
from __future__ import annotations
from pathlib import Path
from hermes_watcher_core.rules import RuleMatcher
from hermes_watcher_core.dedup import DedupStore
from inbox_watcher.runner import run_cycle
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.types import InboxMessage

RULES = """
urgent:
  - id: build_failure
    match: "(Deploy failed|Build failed)"
    description: deploy/build failure
notable:
  - id: payment_dispute
    match: "(dispute|chargeback)"
    description: stripe dispute
ignore:
  - "unsubscribe"
"""


def _msg(mid, vendor, subj):
    return InboxMessage(message_id=mid, vendor=vendor, from_addr=f"x@{vendor}.com",
                        subject=subj, text=subj, ts="2026-06-02T10:00:00+00:00",
                        link="https://app.agentmail.to/"+mid, raw=subj)


class FakeFetcher:
    def __init__(self, msgs): self._m = msgs
    def fetch(self): return iter(self._m)


def _run(tmp_path, msgs):
    rules = RuleMatcher.from_yaml(RULES)
    dedup = DedupStore(tmp_path / "dedup.sqlite3")
    findings = InboxFindingsWriter(tmp_path / "findings", run_date="2026-06-02")
    try:
        return run_cycle(fetcher=FakeFetcher(msgs), rules=rules, dedup=dedup,
                         findings=findings), tmp_path
    finally:
        dedup.close()


def test_urgent_maps_to_p1_and_writes_finding(tmp_path: Path):
    summary, root = _run(tmp_path, [_msg("m1", "vercel", "Deploy failed on prod")])
    rows = InboxFindingsWriter.read_day(root / "findings", "2026-06-02")
    assert len(rows) == 1
    assert rows[0]["priority"] == "P1"
    assert rows[0]["rule_id"] == "build_failure"
    assert summary["P1"] == 1


def test_unmatched_is_p3_unclassified(tmp_path: Path):
    _, root = _run(tmp_path, [_msg("m2", "github", "Your weekly digest")])
    rows = InboxFindingsWriter.read_day(root / "findings", "2026-06-02")
    assert rows[0]["priority"] == "P3"
    assert rows[0]["rule_id"] == "unclassified"


def test_ignore_rule_drops_message(tmp_path: Path):
    summary, root = _run(tmp_path, [_msg("m3", "vercel", "unsubscribe from these emails")])
    rows = InboxFindingsWriter.read_day(root / "findings", "2026-06-02")
    assert rows == []
    assert summary["dropped"] == 1


def test_duplicate_subject_suppressed_second_time(tmp_path: Path):
    summary, root = _run(tmp_path, [
        _msg("m4", "vercel", "Deploy failed on prod"),
        _msg("m5", "vercel", "Deploy failed on prod"),
    ])
    rows = InboxFindingsWriter.read_day(root / "findings", "2026-06-02")
    decisions = sorted(r["dedup_decision"] for r in rows)
    assert decisions == ["send", "suppress_dedup"]
