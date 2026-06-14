"""Seeded end-to-end: ingest (stub fetcher) -> resolve repo -> findings ->
dry-run dispatch. Proves the whole input layer produces a signed, idempotent,
whitelisted payload, and that a spoof is never dispatched."""
import json
from inbox_watcher.types import InboxMessage
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.runner import run_cycle
from inbox_watcher.repo_resolver import load_repo_map, make_resolver
from inbox_watcher.dispatcher import dispatch_cycle, load_fix_hints
from inbox_watcher.ledger import DispatchLedger
from hermes_watcher_core.rules import RuleMatcher
from hermes_watcher_core.dedup import DedupStore

REPO_MAP_YAML = """
extractors:
  vercel: '(?i)project[:/ ]+(?P<project>[a-z0-9][a-z0-9-]{0,99})'
mappings:
  - vendor: vercel
    project: nexus-prod
    repo: uncensored-chatbot
"""
RULES_YAML = (
    "urgent:\n"
    "  - id: vercel_deploy_failed\n    match: \"(?i)build failed\"\n"
    "    fix_hint: keep the fix minimal\n"
    "ignore:\n  - \"(?i)unsubscribe\"\n"
)


def _msg(mid, vendor, text):
    return InboxMessage(message_id=mid, vendor=vendor, from_addr=f"ci@{vendor}.com",
                        subject="Deployment failed", text=text,
                        ts="2026-06-03T00:00:00+00:00", link="https://agentmail/x",
                        raw=f"Deployment failed\n{text}")


def test_seeded_flow_dispatches_once_skips_repeat_and_quarantines_spoof(tmp_path):
    # --- setup ---
    (tmp_path / "repo_map.yaml").write_text(REPO_MAP_YAML)
    (tmp_path / "rules.yaml").write_text(RULES_YAML)
    resolver = make_resolver(load_repo_map(tmp_path / "repo_map.yaml"))
    rules = RuleMatcher.from_yaml(tmp_path / "rules.yaml")
    fix_hints = load_fix_hints(tmp_path / "rules.yaml")
    findings_dir = tmp_path / "findings"

    messages = [
        _msg("<real@h>", "vercel", "Project: nexus-prod build failed"),     # actionable
        _msg("<spoof@h>", "vercel", "Project: evil-repo build failed"),     # extracts, unmapped
    ]

    class StubFetcher:
        def fetch(self):
            yield from messages

    dedup = DedupStore(tmp_path / "dedup.sqlite3")
    findings = InboxFindingsWriter(findings_dir, run_date="2026-06-03")
    run_cycle(fetcher=StubFetcher(), rules=rules, dedup=dedup, findings=findings,
              resolve_repo=resolver)
    dedup.close()

    rows = InboxFindingsWriter.read_day(findings_dir, "2026-06-03")
    repos = {r["message_id"]: r["repo"] for r in rows}
    assert repos["<real@h>"] == "uncensored-chatbot"
    assert repos["<spoof@h>"] is None        # spoof did not resolve to a repo

    # --- dispatch (dry-run) ---
    ledger = DispatchLedger(tmp_path / "dispatched.jsonl")
    emitted = []
    res = dispatch_cycle(findings_rows=rows, ledger=ledger, fix_hints=fix_hints,
                         secret="s3cret", mode="dry_run", emit=emitted.append, now="t0")
    assert res["dispatched"] == 1 and res["considered"] == 1   # only the real one
    env = emitted[0]
    assert env["payload"]["repo"] == "uncensored-chatbot"
    assert env["payload"]["fix_hint"] == "keep the fix minimal"
    # No email prose leaked into the payload:
    for forbidden in ("subject", "text", "raw", "link"):
        assert forbidden not in env["payload"]
    # Spoof never appears in any emitted payload:
    assert all(e["payload"]["repo"] == "uncensored-chatbot" for e in emitted)

    # --- second pass is idempotent ---
    res2 = dispatch_cycle(findings_rows=rows, ledger=ledger, fix_hints=fix_hints,
                          secret="s3cret", mode="dry_run", emit=emitted.append, now="t1")
    assert res2["dispatched"] == 0 and res2["skipped"] == 1
    assert len(emitted) == 1
