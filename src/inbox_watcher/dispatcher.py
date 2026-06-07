"""Dry-run dispatcher: select actionable findings, build signed payloads, log them.

PHASE A: never calls GitHub. DISPATCH_MODE=live is guarded (NotImplementedError).
The payload is built from a FIXED key whitelist (PAYLOAD_KEYS): no raw body text
(text/raw), links, hashes, or dedup state reach it. The one human-readable field,
`summary`, carries a vendor-prefixed subject snippet ("<vendor>: <subject[:200]>",
set in runner.py) — so the email SUBJECT is present (bounded, escaped downstream),
but no other email prose is. Keep that in mind when building the Phase B Codex prompt.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml
from inbox_watcher.config import Config
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.ledger import DispatchLedger

log = logging.getLogger("inbox_watcher.dispatcher")

ACTIONABLE_PRIORITIES = frozenset({"P1", "P2"})
VALID_MODES = frozenset({"dry_run", "live"})

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
    # NOTE: load_rule_meta() is a superset of this. Prefer it for new callers;
    # this remains for dispatch_cycle's existing fix_hints param.
    if not rules_path.exists():
        return {}
    data = yaml.safe_load(rules_path.read_text()) or {}
    hints: dict[str, str] = {}
    for tier in ("urgent", "notable"):
        for entry in (data.get(tier) or []):
            if isinstance(entry, dict) and entry.get("id") and entry.get("fix_hint"):
                hints[entry["id"]] = str(entry["fix_hint"])
    return hints


def load_rule_meta(rules_path: Path) -> dict[str, dict[str, Any]]:
    """rule_id -> {description, fix_hint, fixer}. OUR config; never email-derived."""
    if not rules_path.exists():
        return {}
    data = yaml.safe_load(rules_path.read_text()) or {}
    meta: dict[str, dict[str, Any]] = {}
    for tier in ("urgent", "notable"):
        for entry in (data.get(tier) or []):
            if isinstance(entry, dict) and entry.get("id"):
                meta[entry["id"]] = {
                    "description": str(entry.get("description", "")),
                    "fix_hint": (str(entry["fix_hint"]) if entry.get("fix_hint") else None),
                    "fixer": bool(entry.get("fixer", False)),
                }
    return meta


def fixer_eligible_rule_ids(rule_meta: dict[str, dict[str, Any]]) -> set[str]:
    return {rid for rid, m in rule_meta.items() if m.get("fixer")}


def dispatch_cycle(*, findings_rows, ledger: DispatchLedger, fix_hints, secret,
                   mode, emit, now, fixer_run=None, fixer_eligible=frozenset()) -> dict[str, int]:
    open_sigs = ledger.open_signatures()
    counts = {"dispatched": 0, "skipped": 0, "considered": 0, "errors": 0, "not_eligible": 0}
    for f in findings_rows:
        if not is_actionable(f):
            continue
        counts["considered"] += 1
        sig = error_signature(f["repo"], f["rule_id"])
        if sig in open_sigs:
            counts["skipped"] += 1
            ledger.record(error_signature=sig, repo=f["repo"], rule_id=f["rule_id"],
                          priority=f["priority"], mode=mode, now=now)  # touch row
            continue
        if mode == "dry_run":
            payload = build_payload(f, fix_hint=fix_hints.get(f["rule_id"]), now=now)
            emit(make_envelope(payload, secret))
            ledger.record(error_signature=sig, repo=f["repo"], rule_id=f["rule_id"],
                          priority=f["priority"], mode=mode, now=now)
            open_sigs.add(sig)
            counts["dispatched"] += 1
        elif mode == "live":
            if f["rule_id"] not in fixer_eligible:
                counts["not_eligible"] += 1
                continue
            payload = build_payload(f, fix_hint=fix_hints.get(f["rule_id"]), now=now)
            try:
                status = fixer_run(make_envelope(payload, secret))  # owns record-before-emit
            except Exception as exc:                                # per-finding isolation
                log.warning("fixer_run crashed for %s: %s", sig[:12], exc)
                counts["errors"] += 1
                open_sigs.add(sig)   # suppress within-cycle retry; cross-run retry still governed by the ledger
                continue
            if status == "skipped_locked":
                counts["skipped"] += 1
            else:                                                   # opened | no_fix | error
                open_sigs.add(sig)
                counts["dispatched"] += 1
        else:
            raise ValueError(f"invalid DISPATCH_MODE: {mode}")
    return counts


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.load()
    if not cfg.dispatch_secret:
        log.error("HERMES_FIXER_DISPATCH_SECRET is empty; refusing to dispatch (fail-closed)")
        return 2
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = InboxFindingsWriter.read_day(cfg.findings_dir, run_date)
    ledger = DispatchLedger(cfg.dispatch_ledger_path)
    fix_hints = load_fix_hints(cfg.rules_path)
    now = datetime.now(timezone.utc).isoformat()

    def emit(envelope):
        log.info("DRY-RUN dispatch envelope: %s", json.dumps(envelope, separators=(",", ":")))

    res = dispatch_cycle(findings_rows=rows, ledger=ledger, fix_hints=fix_hints,
                         secret=cfg.dispatch_secret, mode=cfg.dispatch_mode,
                         emit=emit, now=now)
    log.info("dispatch complete: %s (mode=%s)", res, cfg.dispatch_mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
