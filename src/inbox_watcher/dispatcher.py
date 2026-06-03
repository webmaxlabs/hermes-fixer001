"""Dry-run dispatcher: select actionable findings, build signed payloads, log them.

PHASE A: never calls GitHub. DISPATCH_MODE=live is guarded (NotImplementedError).
The payload is built from a FIXED key whitelist (PAYLOAD_KEYS) so no email prose
(subject/text/raw/link) can ever reach the eventual Codex prompt.
"""
from __future__ import annotations
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
import yaml

ACTIONABLE_PRIORITIES = frozenset({"P1", "P2"})

PAYLOAD_KEYS = (
    "schema_version", "repo", "rule_id", "priority", "error_signature",
    "summary", "fix_hint", "message_id", "dispatched_at",
)


def error_signature(repo: str, rule_id: str) -> str:
    return hashlib.sha256(f"{repo}|{rule_id}".encode("utf-8")).hexdigest()


def is_actionable(finding: dict[str, Any]) -> bool:
    return finding.get("priority") in ACTIONABLE_PRIORITIES and bool(finding.get("repo"))


def build_payload(finding: dict[str, Any], *, fix_hint: str | None, now: str) -> dict[str, Any]:
    repo = finding["repo"]
    rule_id = finding["rule_id"]
    return {
        "schema_version": 1,
        "repo": repo,
        "rule_id": rule_id,
        "priority": finding["priority"],
        "error_signature": error_signature(repo, rule_id),
        "summary": finding.get("summary", ""),
        "fix_hint": fix_hint,
        "message_id": finding.get("message_id", ""),
        "dispatched_at": now,
    }


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()


def make_envelope(payload: dict[str, Any], secret: str) -> dict[str, Any]:
    return {"payload": payload, "signature": sign_payload(payload, secret), "alg": "HMAC-SHA256"}


def load_fix_hints(rules_path: Path) -> dict[str, str]:
    """Map rule_id -> fix_hint from rules.yaml. fix_hint is deterministic, OUR text,
    never email-derived. Rules without a fix_hint are omitted."""
    if not rules_path.exists():
        return {}
    data = yaml.safe_load(rules_path.read_text()) or {}
    hints: dict[str, str] = {}
    for tier in ("urgent", "notable"):
        for entry in (data.get(tier) or []):
            if isinstance(entry, dict) and entry.get("id") and entry.get("fix_hint"):
                hints[entry["id"]] = str(entry["fix_hint"])
    return hints
