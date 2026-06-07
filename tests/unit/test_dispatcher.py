import json
from inbox_watcher.dispatcher import (
    error_signature, is_actionable, build_payload, sign_payload, make_envelope,
    PAYLOAD_KEYS,
)

FINDING = {
    "ts": "2026-06-03T00:00:00+00:00", "vendor": "vercel", "priority": "P1",
    "rule_id": "vercel_deploy_failed", "subject": "Deployment failed",
    "summary": "vercel: Deployment failed", "message_id": "<a@h>",
    "link": "https://agentmail/x", "hash": "abc", "dedup_decision": "send",
    "repo": "nexus-uncensored",
}


def _row(repo="agent-intel-kit", rule="fleet_db_integrity", pri="P1"):
    return {"priority": pri, "repo": repo, "rule_id": rule, "summary": "s", "message_id": "<m>"}


def test_error_signature_stable_and_specific():
    a = error_signature("nexus-uncensored", "vercel_deploy_failed")
    b = error_signature("nexus-uncensored", "vercel_deploy_failed")
    assert a == b and len(a) == 64
    assert a != error_signature("nexus-uncensored", "other_rule")
    assert a != error_signature("boe-generator", "vercel_deploy_failed")


def test_is_actionable_matrix():
    assert is_actionable(FINDING) is True
    assert is_actionable({**FINDING, "priority": "P2"}) is True
    assert is_actionable({**FINDING, "priority": "P3"}) is False
    assert is_actionable({**FINDING, "repo": None}) is False
    assert is_actionable({**FINDING, "repo": ""}) is False


def test_build_payload_only_whitelisted_keys():
    p = build_payload(FINDING, fix_hint="bump the lockfile", now="2026-06-03T01:00:00+00:00")
    assert set(p.keys()) == set(PAYLOAD_KEYS)
    # No email-prose fields leak in.
    for forbidden in ("subject", "text", "raw", "link", "hash", "dedup_decision"):
        assert forbidden not in p
    assert p["repo"] == "nexus-uncensored"
    assert p["error_signature"] == error_signature("nexus-uncensored", "vercel_deploy_failed")
    assert p["fix_hint"] == "bump the lockfile"
    assert p["dispatched_at"] == "2026-06-03T01:00:00+00:00"


def test_sign_payload_deterministic_and_tamper_evident():
    p = build_payload(FINDING, fix_hint=None, now="2026-06-03T01:00:00+00:00")
    s1 = sign_payload(p, "secret")
    s2 = sign_payload(dict(reversed(list(p.items()))), "secret")  # key order must not matter
    assert s1 == s2
    tampered = {**p, "repo": "boe-generator"}
    assert sign_payload(tampered, "secret") != s1
    assert sign_payload(p, "different-secret") != s1


def test_make_envelope_shape():
    p = build_payload(FINDING, fix_hint=None, now="2026-06-03T01:00:00+00:00")
    env = make_envelope(p, "secret")
    assert env["alg"] == "HMAC-SHA256"
    assert env["payload"] == p
    assert env["signature"] == sign_payload(p, "secret")


def test_load_fix_hints_reads_optional_field(tmp_path):
    from inbox_watcher.dispatcher import load_fix_hints
    p = tmp_path / "rules.yaml"
    p.write_text(
        "urgent:\n"
        "  - id: vercel_deploy_failed\n    match: \"x\"\n    fix_hint: check the build logs\n"
        "  - id: no_hint_rule\n    match: \"y\"\n"
        "ignore:\n  - \"(?i)unsubscribe\"\n"
    )
    hints = load_fix_hints(p)
    assert hints["vercel_deploy_failed"] == "check the build logs"
    assert "no_hint_rule" not in hints  # absent hint -> not in map


def test_load_fix_hints_missing_file_returns_empty(tmp_path):
    from inbox_watcher.dispatcher import load_fix_hints
    assert load_fix_hints(tmp_path / "nope.yaml") == {}


def test_shipped_rules_fix_hints_are_strings():
    from pathlib import Path
    from inbox_watcher.dispatcher import load_fix_hints
    hints = load_fix_hints(Path(__file__).resolve().parents[2] / "config" / "rules.yaml")
    assert all(isinstance(v, str) and v for v in hints.values())
    assert len(hints) >= 2


def test_dispatch_cycle_emits_actionable_and_skips_repeat(tmp_path):
    from inbox_watcher.dispatcher import dispatch_cycle
    from inbox_watcher.ledger import DispatchLedger
    led = DispatchLedger(tmp_path / "dispatched.jsonl")
    emitted = []
    rows = [
        FINDING,                                   # actionable P1 + repo
        {**FINDING, "priority": "P3"},             # not actionable
        {**FINDING, "repo": None},                 # not actionable
    ]
    res = dispatch_cycle(findings_rows=rows, ledger=led, fix_hints={}, secret="s",
                         mode="dry_run", emit=emitted.append, now="t0")
    assert res["dispatched"] == 1 and res["skipped"] == 0 and res["considered"] == 1
    assert len(emitted) == 1 and emitted[0]["alg"] == "HMAC-SHA256"

    # Second pass over the same actionable finding -> skipped (idempotent).
    res2 = dispatch_cycle(findings_rows=[FINDING], ledger=led, fix_hints={}, secret="s",
                          mode="dry_run", emit=emitted.append, now="t1")
    assert res2["dispatched"] == 0 and res2["skipped"] == 1 and res2["considered"] == 1
    assert len(emitted) == 1  # nothing new emitted


def test_live_without_eligible_does_nothing(tmp_path):
    from inbox_watcher.dispatcher import dispatch_cycle
    from inbox_watcher.ledger import DispatchLedger
    led = DispatchLedger(tmp_path / "d.jsonl")
    res = dispatch_cycle(findings_rows=[_row()], ledger=led, fix_hints={}, secret="s",
                         mode="live", emit=lambda e: None, now="t0",
                         fixer_run=lambda e: "opened", fixer_eligible=frozenset())
    assert res["not_eligible"] == 1 and res["dispatched"] == 0


def test_load_rule_meta_and_eligibility(tmp_path):
    from inbox_watcher.dispatcher import load_rule_meta, fixer_eligible_rule_ids
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "urgent:\n"
        "  - id: fleet_db_integrity\n    match: x\n    description: DB integrity\n"
        "    fix_hint: make idempotent\n    fixer: true\n"
        "  - id: fleet_auth_failure\n    match: y\n    description: auth\n    fix_hint: rotate\n"
        "  - id: fleet_no_hint\n    match: z\n    description: no hint\n"
    )
    meta = load_rule_meta(rules)
    assert meta["fleet_db_integrity"]["description"] == "DB integrity"
    assert meta["fleet_db_integrity"]["fix_hint"] == "make idempotent"
    assert meta["fleet_db_integrity"]["fixer"] is True
    assert meta["fleet_auth_failure"]["fixer"] is False
    assert meta["fleet_no_hint"]["fix_hint"] is None
    assert fixer_eligible_rule_ids(meta) == {"fleet_db_integrity"}


def test_valid_modes():
    from inbox_watcher.dispatcher import VALID_MODES
    assert VALID_MODES == frozenset({"dry_run", "live"})


def test_live_calls_fixer_only_for_eligible(tmp_path):
    from inbox_watcher.dispatcher import dispatch_cycle
    from inbox_watcher.ledger import DispatchLedger
    led = DispatchLedger(tmp_path / "d.jsonl")
    fired = []
    rows = [_row(rule="fleet_db_integrity"), _row(rule="fleet_auth_failure")]
    res = dispatch_cycle(findings_rows=rows, ledger=led, fix_hints={}, secret="s",
                         mode="live", emit=lambda e: None, now="t0",
                         fixer_run=lambda env: fired.append(env["payload"]["rule_id"]) or "opened",
                         fixer_eligible={"fleet_db_integrity"})
    assert fired == ["fleet_db_integrity"]            # auth not eligible -> not fired
    assert res["dispatched"] == 1


def test_live_per_finding_isolation(tmp_path):
    from inbox_watcher.dispatcher import dispatch_cycle
    from inbox_watcher.ledger import DispatchLedger
    led = DispatchLedger(tmp_path / "d.jsonl")
    def boom(env):
        raise RuntimeError("codex blew up")
    res = dispatch_cycle(findings_rows=[_row()], ledger=led, fix_hints={}, secret="s",
                         mode="live", emit=lambda e: None, now="t0",
                         fixer_run=boom, fixer_eligible={"fleet_db_integrity"})
    assert res["errors"] == 1
    assert res["dispatched"] == 0
    assert res["considered"] == 1


class _FakeCfg:
    def __init__(self, tmp_path, mode="dry_run"):
        self.dispatch_secret = "s"; self.dispatch_mode = mode
        self.findings_dir = tmp_path; self.dispatch_ledger_path = tmp_path / "d.jsonl"
        self.rules_path = tmp_path / "rules.yaml"; self.rules_path.write_text("urgent: []\n")
        self.codex_bin = "codex"; self.codex_timeout_sec = 60; self.github_token = ""
        self.fixer_pr_labels = ["hermes-fixer"]; self.fixer_default_owner = "webmaxlabs"
        self.fixer_workdir = tmp_path / "w"; self.fixer_lock_path = tmp_path / "l"


def test_main_rejects_unknown_mode(tmp_path, monkeypatch):
    import inbox_watcher.dispatcher as D
    from inbox_watcher.config import Config
    monkeypatch.setattr(Config, "load", staticmethod(lambda **kw: _FakeCfg(tmp_path, mode="frobnicate")))
    assert D.main() == 2   # fail-closed on bad mode


def test_main_live_without_token_fails_closed(tmp_path, monkeypatch):
    import inbox_watcher.dispatcher as D
    from inbox_watcher.config import Config
    monkeypatch.setattr(Config, "load", staticmethod(lambda **kw: _FakeCfg(tmp_path, mode="live")))
    assert D.main() == 2   # live requires GITHUB_TOKEN (fail-closed); _FakeCfg has github_token=""


def test_main_fails_closed_without_secret(tmp_path, monkeypatch):
    # CORRECTED: capture the original classmethod and delegate to a tmp env file,
    # rather than the plan's recursive lambda (which infinite-loops).
    import inbox_watcher.dispatcher as d
    env = tmp_path / ".env"
    env.write_text("AGENTMAIL_API_KEY=k\nSLACK_BOT_TOKEN=xoxb-t\n")  # no dispatch secret
    monkeypatch.delenv("HERMES_FIXER_DISPATCH_SECRET", raising=False)
    monkeypatch.delenv("DISPATCH_MODE", raising=False)
    orig = d.Config.load.__func__  # unwrap the classmethod to the plain function
    monkeypatch.setattr(d.Config, "load",
                        classmethod(lambda cls, env_file=None: orig(cls, env_file=env)))
    rc = d.main()
    assert rc == 2  # fail-closed exit code


def test_reconcile_closes_merged_pr(tmp_path, monkeypatch):
    from inbox_watcher.dispatcher import _reconcile
    from inbox_watcher.ledger import DispatchLedger
    import inbox_watcher.github_pr as ghpr
    led = DispatchLedger(tmp_path / "d.jsonl")
    led.record(error_signature="sig1", repo="r", rule_id="x", priority="P1",
               mode="live", now="t0", status="opened", pr_url="https://github.com/o/r/pull/1")
    monkeypatch.setattr(ghpr, "get_pr_state", lambda url, *, token: "merged")
    cfg = _FakeCfg(tmp_path, mode="live"); cfg.github_token = "tok"
    assert _reconcile(cfg) == 0
    row = led.fold()["sig1"]
    assert row["open"] is False and row["status"] == "merged"


def test_reconcile_leaves_open_pr_open(tmp_path, monkeypatch):
    from inbox_watcher.dispatcher import _reconcile
    from inbox_watcher.ledger import DispatchLedger
    import inbox_watcher.github_pr as ghpr
    led = DispatchLedger(tmp_path / "d.jsonl")
    led.record(error_signature="sig1", repo="r", rule_id="x", priority="P1",
               mode="live", now="t0", status="opened", pr_url="https://github.com/o/r/pull/1")
    monkeypatch.setattr(ghpr, "get_pr_state", lambda url, *, token: "open")
    cfg = _FakeCfg(tmp_path, mode="live"); cfg.github_token = "tok"
    assert _reconcile(cfg) == 0
    assert led.fold()["sig1"]["open"] is True   # still open, not closed


def test_reconcile_isolates_get_state_errors(tmp_path, monkeypatch):
    from inbox_watcher.dispatcher import _reconcile
    from inbox_watcher.ledger import DispatchLedger
    import inbox_watcher.github_pr as ghpr
    led = DispatchLedger(tmp_path / "d.jsonl")
    led.record(error_signature="sig1", repo="r", rule_id="x", priority="P1",
               mode="live", now="t0", status="opened", pr_url="https://github.com/o/r/pull/1")
    def boom(url, *, token): raise RuntimeError("api down")
    monkeypatch.setattr(ghpr, "get_pr_state", boom)
    cfg = _FakeCfg(tmp_path, mode="live"); cfg.github_token = "tok"
    assert _reconcile(cfg) == 0                 # error isolated, did not raise
    assert led.fold()["sig1"]["open"] is True   # untouched


def test_main_reconcile_without_token_fails_closed(tmp_path, monkeypatch):
    import inbox_watcher.dispatcher as D
    from inbox_watcher.config import Config
    monkeypatch.setattr(Config, "load", staticmethod(lambda **kw: _FakeCfg(tmp_path, mode="dry_run")))
    assert D.main(["--reconcile"]) == 2   # _FakeCfg github_token="" => fail-closed
