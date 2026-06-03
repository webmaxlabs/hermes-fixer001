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
