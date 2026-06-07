# tests/unit/test_rules.py
from __future__ import annotations
import pytest
from pathlib import Path
from hermes_watcher_core.rules import RuleMatcher

RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "rules.yaml"


def _matcher():
    return RuleMatcher.from_yaml(RULES_PATH)


def test_rules_compile():
    assert _matcher() is not None


def test_marketing_blast_is_ignored():
    r = _matcher().match("Unsubscribe — weekly product newsletter")
    assert r is not None and r.tier == "ignore"


TAXONOMY_CASES = [
    ("[URGENT] vercel-log-watcher: x — haiku:[auth][error].*401", "fleet_auth_failure", "urgent"),
    ("[URGENT] vercel-log-watcher: x — haiku:compliance.*duplicate key", "fleet_db_integrity", "urgent"),
    ("[URGENT] uptime-watcher: agentintelkit DOWN — request error", "fleet_site_down", "urgent"),
    ("[URGENT] uptime-watcher: cert-expiry — cert_expiry:2d", "fleet_cert_expiry", "urgent"),
    ("uptime-watcher: cert-expiry — cert_expiry:11d", "fleet_cert_expiry_warn", "notable"),
    ("[URGENT] stripe-watcher: agent-intel-kit — stripe_error:charge_failed:processing_error",
     "fleet_stripe_error", "urgent"),
    ("[URGENT] some-watcher: y — haiku:whatever", "fleet_urgent", "urgent"),
]


@pytest.mark.parametrize("subject,rule_id,tier", TAXONOMY_CASES)
def test_taxonomy_classification(subject, rule_id, tier):
    r = _matcher().match(subject)
    assert r is not None and r.rule_id == rule_id and r.tier == tier


def test_stripe_error_is_notify_only():
    import yaml
    data = yaml.safe_load(RULES_PATH.read_text())
    rule = next(e for e in data["urgent"] if e["id"] == "fleet_stripe_error")
    assert "fixer" not in rule  # notify-only: a revoked key / Stripe-side failure is human-investigated


def test_stripe_decline_subject_is_never_emitted_so_no_rule_matches_declines():
    # sanity: a plain decline never reaches inbox-watcher (stripe-watcher suppresses it),
    # and no rule should accidentally classify the word "card_declined" as urgent.
    r = _matcher().match("Re: card_declined on my personal card")
    assert r is None


def test_cert_warn_requires_uptime_watcher_anchor():
    # a stray mention of cert_expiry without the watcher anchor must NOT classify as notable
    r = _matcher().match("Re: some thread mentioning cert_expiry in passing")
    assert r is None   # falls through to P3 unclassified, not P2


def test_vestigial_native_rules_removed():
    import yaml
    data = yaml.safe_load(RULES_PATH.read_text())
    ids = {e["id"] for tier in ("urgent", "notable") for e in (data.get(tier) or [])}
    for dead in ("vercel_deploy_failed", "stripe_payment_failed", "stripe_key_or_account",
                 "uptime_down", "stripe_dispute", "github_security_alert",
                 "github_failed_workflow", "usage_or_billing"):
        assert dead not in ids
    # only fleet_* rules remain
    assert all(i.startswith("fleet_") for i in ids), ids
