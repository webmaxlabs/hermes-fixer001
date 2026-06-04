"""Thin inbox runner: fetch -> classify -> dedup -> write rich findings."""
from __future__ import annotations
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable
from hermes_watcher_core.dedup import AlertDecision, DedupStore
from hermes_watcher_core.rules import RuleMatcher
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.types import InboxFinding

log = logging.getLogger("inbox_watcher.runner")

_PRIORITY_BY_TIER = {"urgent": "P1", "notable": "P2"}


def run_cycle(*, fetcher, rules: RuleMatcher, dedup: DedupStore,
              findings: InboxFindingsWriter,
              resolve_repo: Callable[[str, str], str | None] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    counts = {"P1": 0, "P2": 0, "P3": 0, "dropped": 0}
    # NB: quarantined messages are dropped + logged at INFO inside AgentMailFetcher.fetch(),
    # before they reach run_cycle, so they are intentionally not counted here.

    for msg in fetcher.fetch():
        try:
            res = rules.match(msg.raw)
            if res is not None and res.tier == "ignore":
                counts["dropped"] += 1
                continue
            if res is None:
                # Unmatched authenticated mail = notify-only P3. We pass tier "notable"
                # to dedup so it's suppressed like a non-urgent finding (never an immediate
                # SEND), even though the finding's own priority is P3.
                priority, rule_id, tier = "P3", "unclassified", "notable"
            else:
                tier = res.tier
                priority = _PRIORITY_BY_TIER.get(tier, "P3")
                rule_id = res.rule_id or "unclassified"

            # Dedup on the same text the classifier matched (msg.raw), so body-only
            # matches suppress correctly. DedupStore.normalize() strips noise.
            decision = dedup.record(source_id=msg.vendor, tier=tier,
                                    rule_id=rule_id, message=msg.raw)
            h = dedup.hash_finding(msg.vendor, rule_id, msg.raw)
            counts[priority] += 1
            repo = None
            if resolve_repo is not None:
                repo = resolve_repo(msg.vendor, msg.text or msg.raw)
            findings.write_finding(InboxFinding(
                ts=msg.ts or _now(), vendor=msg.vendor, priority=priority,
                rule_id=rule_id, subject=msg.subject[:300],
                summary=f"{msg.vendor}: {msg.subject[:200]}",
                message_id=msg.message_id, link=msg.link, hash=h,
                dedup_decision=decision.value, repo=repo,
            ))
        except Exception as exc:                            # per-message isolation
            log.warning("classify/write failed for %s: %s", getattr(msg, "message_id", "?"), exc)
            findings.write_error({"ts": _now(), "message_id": getattr(msg, "message_id", ""),
                                  "error": f"{type(exc).__name__}: {exc}",
                                  "trace": traceback.format_exc()})
            continue

    deleted = dedup.cleanup(older_than_days=14)
    summary = {"ts": _now(), "duration_sec": round(time.monotonic() - started, 2),
               **counts, "dedup_pruned": deleted}
    findings.write_run_summary(summary)
    return summary


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
