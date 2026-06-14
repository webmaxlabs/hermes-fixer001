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

# A fix is recoverable once its in_progress row is older than this (well past the
# codex timeout + clone/push, so we never disturb an in-flight fix), capped to avoid
# burning quota retrying a persistently-failing repo forever.
STALE_FIX_SECONDS = 1800
MAX_FIX_ATTEMPTS = 3

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


def recover_stale_fixes(ledger: DispatchLedger, *, now: str,
                        stale_seconds: int = STALE_FIX_SECONDS,
                        max_attempts: int = MAX_FIX_ATTEMPTS) -> dict[str, int]:
    """Re-enable or retire fixes stuck in `in_progress`.

    A codex timeout/crash leaves a row in_progress+open (no PR), which the dedup gate
    would skip forever. The fixer is synchronous + lockfile-guarded, so any in_progress
    row older than stale_seconds is a dead attempt, never an in-flight one. We flip it
    back to dispatchable (open=False) up to max_attempts, then mark it `failed` (loudly)
    so a human is alerted. Double-PR safety lives in run_fixer's find_open_pr guard.
    """
    now_dt = datetime.fromisoformat(now)
    counts = {"retried": 0, "exhausted": 0}
    for sig, row in ledger.fold().items():
        if not (row.get("open") and row.get("status") == "in_progress"):
            continue
        stamp = row.get("last_seen_ts") or row.get("first_dispatched_ts")
        if stamp:
            try:
                if (now_dt - datetime.fromisoformat(stamp)).total_seconds() < stale_seconds:
                    continue  # may still be running
            except ValueError:
                pass
        attempts = int(row.get("fix_attempts", 0))
        common = dict(error_signature=sig, repo=row["repo"], rule_id=row["rule_id"],
                      priority=row["priority"], mode="live", now=now)
        if attempts >= max_attempts:
            ledger.record(**common, status="failed", open=True, fix_attempts=attempts)
            log.error("fixer GAVE UP on %s (%s) after %d attempts stuck in_progress; needs a human",
                      row["repo"], sig[:12], attempts)
            counts["exhausted"] += 1
        else:
            ledger.record(**common, status="retry_pending", open=False, fix_attempts=attempts + 1)
            log.info("re-enabling stale fix %s (%s) for retry (attempt %d/%d)",
                     row["repo"], sig[:12], attempts + 1, max_attempts)
            counts["retried"] += 1
    return counts


def _build_fixer_run(cfg, rule_meta):
    from inbox_watcher.fixer import run_fixer, FixerDeps
    from inbox_watcher import gitops, codex_runner, github_pr
    from inbox_watcher.ledger import DispatchLedger
    ledger = DispatchLedger(cfg.dispatch_ledger_path)
    deps = FixerDeps(
        clone=gitops.clone, run_codex=codex_runner.run_codex, has_changes=gitops.has_changes,
        commit_branch_push=gitops.commit_branch_push, open_draft_pr=github_pr.open_draft_pr,
        find_open_pr=github_pr.find_open_pr_for_head,
        ledger=ledger, rule_meta=rule_meta, workdir=cfg.fixer_workdir, lock_path=cfg.fixer_lock_path,
        owner=cfg.fixer_default_owner, base="main", labels=cfg.fixer_pr_labels,
        token=cfg.github_token, codex_bin=cfg.codex_bin, timeout_sec=cfg.codex_timeout_sec)
    now_iso = datetime.now(timezone.utc).isoformat()
    return lambda envelope: run_fixer(envelope["payload"], deps=deps, now=now_iso)


def main(argv=None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.load()
    if cfg.dispatch_mode not in VALID_MODES:
        log.error("invalid DISPATCH_MODE %r (allowed: %s); fail-closed", cfg.dispatch_mode, sorted(VALID_MODES))
        return 2
    if not cfg.dispatch_secret:
        log.error("HERMES_FIXER_DISPATCH_SECRET is empty; refusing to dispatch (fail-closed)")
        return 2
    if cfg.dispatch_mode == "live" and not cfg.github_token:
        log.error("DISPATCH_MODE=live requires GITHUB_TOKEN; refusing to dispatch (fail-closed)")
        return 2
    if "--reconcile" in argv:
        if not cfg.github_token:
            log.error("--reconcile requires GITHUB_TOKEN; refusing (fail-closed)")
            return 2
        return _reconcile(cfg)
    if cfg.dispatch_mode == "live":
        from inbox_watcher import codex_runner
        if not codex_runner.codex_logged_in(cfg.codex_bin):
            log.error("DISPATCH_MODE=live but Codex is not logged in (%s login status); refusing "
                      "to dispatch so findings retry next cycle instead of burning (fail-closed)",
                      cfg.codex_bin)
            return 2
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = InboxFindingsWriter.read_day(cfg.findings_dir, run_date)
    ledger = DispatchLedger(cfg.dispatch_ledger_path)
    rule_meta = load_rule_meta(cfg.rules_path)
    fix_hints = {rid: m["fix_hint"] for rid, m in rule_meta.items() if m.get("fix_hint")}
    now = datetime.now(timezone.utc).isoformat()

    if cfg.dispatch_mode == "live":
        rec = recover_stale_fixes(ledger, now=now)
        if rec["retried"] or rec["exhausted"]:
            log.info("stale-fix recovery: %s", rec)

    def emit(envelope):
        log.info("DRY-RUN dispatch envelope: %s", json.dumps(envelope, separators=(",", ":")))

    fixer_run = _build_fixer_run(cfg, rule_meta) if cfg.dispatch_mode == "live" else None
    res = dispatch_cycle(findings_rows=rows, ledger=ledger, fix_hints=fix_hints,
                         secret=cfg.dispatch_secret, mode=cfg.dispatch_mode, emit=emit, now=now,
                         fixer_run=fixer_run, fixer_eligible=fixer_eligible_rule_ids(rule_meta))
    log.info("dispatch complete: %s (mode=%s)", res, cfg.dispatch_mode)
    return 0


def _reconcile(cfg) -> int:
    from inbox_watcher import github_pr
    from inbox_watcher.ledger import DispatchLedger
    ledger = DispatchLedger(cfg.dispatch_ledger_path)
    now = datetime.now(timezone.utc).isoformat()
    closed = 0
    for sig, row in ledger.fold().items():
        if row.get("open") and row.get("status") == "opened" and row.get("pr_url"):
            try:
                state = github_pr.get_pr_state(row["pr_url"], token=cfg.github_token)
            except Exception as exc:
                log.warning("reconcile: cannot read %s: %s", row["pr_url"], exc)
                continue
            if state in ("merged", "closed"):
                ledger.record(error_signature=sig, repo=row["repo"], rule_id=row["rule_id"],
                              priority=row["priority"], mode="live", now=now,
                              status=state, pr_url=row["pr_url"], open=False)
                closed += 1
    log.info("reconcile complete: closed=%d", closed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
