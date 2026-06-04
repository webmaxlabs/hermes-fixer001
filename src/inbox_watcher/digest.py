"""Daily Slack digest: read findings, rank, post to #hermes-digest."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Callable
import httpx
from inbox_watcher.config import Config
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.dispatcher import is_actionable, error_signature

log = logging.getLogger("inbox_watcher.digest")
_ORDER = {"P1": 0, "P2": 1, "P3": 2}


def _slack_escape(s: str) -> str:
    # Slack mrkdwn treats & < > as special; < > also gate <!channel> and <url|text>.
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def dedupe_rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per unique hash (prefer a non-suppressed copy), ranked P1->P3."""
    by_hash: dict[str, dict[str, Any]] = {}
    for r in rows:
        h = r.get("hash", "")
        if h not in by_hash or r.get("dedup_decision") != "suppress_dedup":
            by_hash.setdefault(h, r)
            if r.get("dedup_decision") != "suppress_dedup":
                by_hash[h] = r
    uniq = list(by_hash.values())
    return sorted(uniq, key=lambda r: (_ORDER.get(r.get("priority", "P3"), 3),
                                       r.get("vendor", "")))


def build_digest_text(ranked: list[dict[str, Any]], *, run_date: str) -> str:
    if not ranked:
        return f"*Inbox triage -- {run_date}*\nNo new alerts. :white_check_mark:"
    lines = [f"*Inbox triage -- {run_date}*  ({len(ranked)} alert(s))"]
    current = None
    for r in ranked:
        prio = r.get("priority", "P3")
        if prio != current:
            current = prio
            lines.append(f"\n*{prio}*")
        line = f"• [{r.get('vendor','?')}] {_slack_escape(r.get('subject',''))}  <{r.get('link','')}|view>"
        if is_actionable(r):
            sig = error_signature(r["repo"], r.get("rule_id", "unclassified"))[:8]
            line += f"  _→ would dispatch → {_slack_escape(r['repo'])} (sig {sig})_"
        lines.append(line)
    return "\n".join(lines)


def _slack_poster(token: str) -> Callable[[str, str], bool]:
    def post(channel: str, text: str) -> bool:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": channel, "text": text, "unfurl_links": False},
            timeout=15,
        )
        ok = resp.status_code == 200 and resp.json().get("ok", False)
        if not ok:
            log.error("slack post failed: %s %s", resp.status_code, resp.text[:300])
        return ok
    return post


def post_digest(rows: list[dict[str, Any]], *, run_date: str, channel: str,
                poster: Callable[[str, str], bool]) -> bool:
    ranked = dedupe_rank(rows)
    return poster(channel, build_digest_text(ranked, run_date=run_date))


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.load()
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = InboxFindingsWriter.read_day(cfg.findings_dir, run_date)
    ok = post_digest(rows, run_date=run_date, channel=cfg.slack_channel,
                     poster=_slack_poster(cfg.slack_bot_token))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
