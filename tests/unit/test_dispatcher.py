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
    assert res == {"dispatched": 1, "skipped": 0, "considered": 1}
    assert len(emitted) == 1 and emitted[0]["alg"] == "HMAC-SHA256"

    # Second pass over the same actionable finding -> skipped (idempotent).
    res2 = dispatch_cycle(findings_rows=[FINDING], ledger=led, fix_hints={}, secret="s",
                          mode="dry_run", emit=emitted.append, now="t1")
    assert res2 == {"dispatched": 0, "skipped": 1, "considered": 1}
    assert len(emitted) == 1  # nothing new emitted


def test_dispatch_cycle_live_mode_is_guarded(tmp_path):
    import pytest
    from inbox_watcher.dispatcher import dispatch_cycle
    from inbox_watcher.ledger import DispatchLedger
    led = DispatchLedger(tmp_path / "dispatched.jsonl")
    with pytest.raises(NotImplementedError):
        dispatch_cycle(findings_rows=[FINDING], ledger=led, fix_hints={}, secret="s",
                       mode="live", emit=lambda e: None, now="t0")


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
