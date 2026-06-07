from pathlib import Path
from dataclasses import dataclass, replace
from inbox_watcher.fixer import run_fixer, FixerDeps
from inbox_watcher.ledger import DispatchLedger


def _payload():
    return {"repo": "agent-intel-kit", "rule_id": "fleet_db_integrity", "priority": "P1",
            "error_signature": "sig1", "summary": "webmax: [URGENT] secret-subject",
            "fix_hint": "idempotent", "message_id": "<m>"}


def _deps(tmp_path, *, changes: bool, codex_ok: bool = True):
    led = DispatchLedger(tmp_path / "d.jsonl")
    rec = {"clone": [], "codex_prompts": [], "push": [], "pr": []}
    def clone(url, dest, **kw): rec["clone"].append((url, str(dest))); Path(dest).mkdir(parents=True, exist_ok=True)
    def run_codex(*, clone_dir, prompt, **kw):
        rec["codex_prompts"].append(prompt)
        class R: ok = codex_ok; stdout = ""; stderr = "" if codex_ok else "boom"
        return R()
    def has_changes(d, **kw): return changes
    def commit_branch_push(d, *, branch, message, **kw): rec["push"].append(branch)
    def open_draft_pr(**kw): rec["pr"].append(kw); return "https://github.com/webmaxlabs/agent-intel-kit/pull/1"
    deps = FixerDeps(
        clone=clone, run_codex=run_codex, has_changes=has_changes,
        commit_branch_push=commit_branch_push, open_draft_pr=open_draft_pr, ledger=led,
        rule_meta={"fleet_db_integrity": {"description": "DB integrity", "fix_hint": "idempotent", "fixer": True}},
        workdir=tmp_path / "work", lock_path=tmp_path / "fixer.lock",
        owner="webmaxlabs", base="main", labels=["hermes-fixer"], token="tok",
        codex_bin="codex", timeout_sec=60)
    return deps, rec, led


def test_changes_open_draft_pr_and_record_opened(tmp_path):
    deps, rec, led = _deps(tmp_path, changes=True)
    status = run_fixer(_payload(), deps=deps, now="t0")
    assert status == "opened"
    assert rec["push"] and rec["pr"]
    folded = led.fold()["sig1"]
    assert folded["status"] == "opened" and folded["pr_url"].endswith("/pull/1")


def test_no_changes_records_no_fix_and_opens_no_pr(tmp_path):
    deps, rec, led = _deps(tmp_path, changes=False)
    status = run_fixer(_payload(), deps=deps, now="t0")
    assert status == "no_fix"
    assert rec["pr"] == []
    assert led.fold()["sig1"]["status"] == "no_fix"


def test_prompt_has_no_email_summary(tmp_path):
    deps, rec, led = _deps(tmp_path, changes=True)
    run_fixer(_payload(), deps=deps, now="t0")
    assert rec["codex_prompts"]
    assert "secret-subject" not in rec["codex_prompts"][0]  # email text never reaches Codex


def test_records_in_progress_before_acting(tmp_path):
    # if codex fails, the signature is already open (record-before-emit) so it won't retry
    deps, rec, led = _deps(tmp_path, changes=False, codex_ok=False)
    status = run_fixer(_payload(), deps=deps, now="t0")
    assert status == "error"  # new guard rejects failed codex before has_changes
    assert "sig1" in led.open_signatures()


def test_lock_held_skips(tmp_path):
    deps, rec, led = _deps(tmp_path, changes=True)
    import fcntl
    fh = open(deps.lock_path, "w"); fcntl.flock(fh, fcntl.LOCK_EX)
    try:
        assert run_fixer(_payload(), deps=deps, now="t0") == "skipped_locked"
        assert led.fold() == {}  # nothing recorded before the lock is acquired
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


def test_codex_failure_returns_error_and_leaves_open(tmp_path):
    deps, rec, led = _deps(tmp_path, changes=True, codex_ok=False)
    status = run_fixer(_payload(), deps=deps, now="t0")
    assert status == "error"
    assert rec["pr"] == []                      # no PR on a failed codex run
    assert "sig1" in led.open_signatures()      # left open, no retry


def test_clone_failure_returns_error_and_leaves_open(tmp_path):
    deps, rec, led = _deps(tmp_path, changes=False)
    def bad_clone(url, dest, **kw): raise RuntimeError("network failure")
    deps = replace(deps, clone=bad_clone)
    status = run_fixer(_payload(), deps=deps, now="t0")
    assert status == "error"
    assert "sig1" in led.open_signatures()
