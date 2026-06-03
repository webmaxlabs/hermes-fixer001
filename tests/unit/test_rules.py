# tests/unit/test_rules.py
from __future__ import annotations
from pathlib import Path
from hermes_watcher_core.rules import RuleMatcher

RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "rules.yaml"


def _matcher():
    return RuleMatcher.from_yaml(RULES_PATH)


def test_rules_compile():
    assert _matcher() is not None


def test_vercel_deploy_failure_is_urgent():
    r = _matcher().match("Deployment to production failed for boe-generator")
    assert r is not None and r.tier == "urgent"


def test_stripe_dispute_is_notable():
    r = _matcher().match("A payment has been disputed (chargeback) for $40.00")
    assert r is not None and r.tier == "notable"


def test_marketing_blast_is_ignored():
    r = _matcher().match("Unsubscribe — weekly product newsletter")
    assert r is not None and r.tier == "ignore"
