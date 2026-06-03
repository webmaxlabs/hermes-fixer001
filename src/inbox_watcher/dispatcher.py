"""Dry-run dispatcher: select actionable findings, build signed payloads, log them.

PHASE A: never calls GitHub. DISPATCH_MODE=live is guarded (NotImplementedError).
The payload is built from a FIXED key whitelist (PAYLOAD_KEYS) so no email prose
(subject/text/raw/link) can ever reach the eventual Codex prompt.
"""
from __future__ import annotations
import hashlib
import hmac
import json
from typing import Any

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
