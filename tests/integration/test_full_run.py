# tests/integration/test_full_run.py
from __future__ import annotations
from types import SimpleNamespace
from pathlib import Path
from hermes_watcher_core.rules import RuleMatcher
from hermes_watcher_core.dedup import DedupStore
from inbox_watcher.agentmail import AgentMailFetcher
from inbox_watcher.auth import ALLOWED_FROM_DOMAINS
from inbox_watcher.cursor import Cursor
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.runner import run_cycle

RULES = (Path(__file__).resolve().parent.parent.parent / "config" / "rules.yaml")


def _full(mid, frm, subj, ts, dkim="pass", to="alerts@webmaxlabs.com"):
    d = frm.split("@")[-1]
    return SimpleNamespace(message_id=mid, from_=frm, to=[to], subject=subj, text=subj,
                           timestamp=ts,
                           headers={"Authentication-Results": f"x; dkim={dkim} header.d={d}; dmarc={dkim} header.from={d}"})


class FakeMessages:
    def __init__(self, msgs): self._msgs = msgs
    def list(self, **kw): return SimpleNamespace(messages=list(self._msgs.values()), next_page_token=None)
    def get(self, *, inbox_id, message_id): return self._msgs[message_id]


class FakeClient:
    def __init__(self, msgs): self.inboxes = SimpleNamespace(messages=FakeMessages(msgs))


def test_end_to_end_classifies_and_quarantines_spoof(tmp_path: Path):
    msgs = {
        "m1": _full("m1", "alerts@vercel.com", "Deployment to production failed", "2026-06-02T10:00:00+00:00"),
        "m2": _full("m2", "billing@stripe.com", "A payment has been disputed", "2026-06-02T10:01:00+00:00"),
        "m3": _full("m3", "noreply@github.com", "Repository access changed for webmaxlabs/boe-generator", "2026-06-02T10:02:00+00:00"),
        "spoof": _full("spoof", "attacker@vercel.com", "Deployment failed", "2026-06-02T10:03:00+00:00", dkim="fail"),
    }
    client = FakeClient(msgs)
    cursor = Cursor(tmp_path / "cursor.json")
    fetcher = AgentMailFetcher(client=client, inbox_id="i", cursor=cursor,
                               allowed_domains=ALLOWED_FROM_DOMAINS)
    rules = RuleMatcher.from_yaml(RULES)
    dedup = DedupStore(tmp_path / "dedup.sqlite3")
    findings = InboxFindingsWriter(tmp_path / "findings", run_date="2026-06-02")
    try:
        summary = run_cycle(fetcher=fetcher, rules=rules, dedup=dedup, findings=findings)
    finally:
        dedup.close()

    rows = InboxFindingsWriter.read_day(tmp_path / "findings", "2026-06-02")
    by_id = {r["message_id"]: r for r in rows}
    # Native vendor mail (vercel.com, stripe.com, github.com) never arrives in production —
    # only fleet relays from alerts@webmaxlabs.com do. Rules for those sources were removed.
    # All three messages here are native-vendor subjects with no matching fleet rule → P3.
    assert by_id["m1"]["priority"] == "P3"        # "Deployment to production failed" — no fleet rule fires
    assert by_id["m1"]["rule_id"] == "unclassified"
    assert by_id["m2"]["priority"] == "P3"        # "A payment has been disputed" — no fleet rule fires
    assert by_id["m2"]["rule_id"] == "unclassified"
    assert by_id["m3"]["priority"] == "P3"        # "Repository access changed..." — no fleet rule fires
    assert by_id["m3"]["rule_id"] == "unclassified"
    assert "spoof" not in by_id                    # dkim=fail spoof never reached findings
    assert summary["P1"] == 0 and summary["P2"] == 0 and summary["P3"] == 3
