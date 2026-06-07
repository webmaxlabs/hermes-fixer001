# tests/integration/test_fixer_flow.py
from pathlib import Path
from inbox_watcher.dispatcher import dispatch_cycle, load_rule_meta, fixer_eligible_rule_ids, error_signature
from inbox_watcher.fixer import run_fixer, FixerDeps
from inbox_watcher.ledger import DispatchLedger


def test_full_live_emit_opens_pr_with_stub_codex(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "urgent:\n  - id: fleet_db_integrity\n    match: x\n    description: DB integrity\n"
        "    fix_hint: idempotent\n    fixer: true\n")
    meta = load_rule_meta(rules)
    led = DispatchLedger(tmp_path / "d.jsonl")
    pr_calls = []

    def clone(url, dest, **kw): Path(dest).mkdir(parents=True, exist_ok=True)
    def run_codex(*, clone_dir, prompt, **kw):
        (Path(clone_dir) / "fix.py").write_text("# fix\n")   # stub codex writes a file
        class R: ok = True; stdout = "patched"; stderr = ""
        return R()
    def has_changes(d, **kw): return True
    def commit_branch_push(d, *, branch, message, **kw): pass
    def open_draft_pr(**kw): pr_calls.append(kw); return "https://github.com/webmaxlabs/agent-intel-kit/pull/9"

    deps = FixerDeps(clone=clone, run_codex=run_codex, has_changes=has_changes,
                     commit_branch_push=commit_branch_push, open_draft_pr=open_draft_pr,
                     ledger=led, rule_meta=meta, workdir=tmp_path / "w", lock_path=tmp_path / "l",
                     owner="webmaxlabs", base="main", labels=["hermes-fixer"], token="tok",
                     codex_bin="codex", timeout_sec=60)
    rows = [{"priority": "P1", "repo": "agent-intel-kit", "rule_id": "fleet_db_integrity",
             "summary": "secret", "message_id": "<m>"}]
    res = dispatch_cycle(findings_rows=rows, ledger=led, fix_hints={}, secret="s", mode="live",
                         emit=lambda e: None, now="t0",
                         fixer_run=lambda env: run_fixer(env["payload"], deps=deps, now="t0"),
                         fixer_eligible=fixer_eligible_rule_ids(meta))
    assert res["dispatched"] == 1 and res["errors"] == 0
    assert pr_calls and pr_calls[0]["labels"] == ["hermes-fixer", "P1"]
    sig = error_signature("agent-intel-kit", "fleet_db_integrity")
    assert led.fold()[sig]["status"] == "opened"
    assert led.fold()[sig]["pr_url"].endswith("/pull/9")

    # idempotent: a second cycle with the same finding skips (already open)
    res2 = dispatch_cycle(findings_rows=rows, ledger=led, fix_hints={}, secret="s", mode="live",
                          emit=lambda e: None, now="t1",
                          fixer_run=lambda env: run_fixer(env["payload"], deps=deps, now="t1"),
                          fixer_eligible=fixer_eligible_rule_ids(meta))
    assert res2["skipped"] == 1 and res2["dispatched"] == 0
    assert len(pr_calls) == 1   # idempotent: no second PR opened
