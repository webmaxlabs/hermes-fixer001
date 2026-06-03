"""Ingest entrypoint: python -m inbox_watcher"""
from __future__ import annotations
import logging
from agentmail import AgentMail
from hermes_watcher_core.dedup import DedupStore
from hermes_watcher_core.rules import RuleMatcher
from inbox_watcher.agentmail import AgentMailFetcher
from inbox_watcher.auth import ALLOWED_FROM_DOMAINS
from inbox_watcher.config import Config
from inbox_watcher.cursor import Cursor
from inbox_watcher.findings import InboxFindingsWriter
from inbox_watcher.runner import run_cycle
from datetime import datetime, timezone


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.load()
    client = AgentMail(api_key=cfg.agentmail_api_key)
    cursor = Cursor(cfg.data_dir / "cursor.json")
    fetcher = AgentMailFetcher(client=client, inbox_id=cfg.inbox_id, cursor=cursor,
                               allowed_domains=ALLOWED_FROM_DOMAINS)
    rules = RuleMatcher.from_yaml(cfg.rules_path)
    dedup = DedupStore(cfg.data_dir / "dedup.sqlite3")
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    findings = InboxFindingsWriter(cfg.findings_dir, run_date=run_date)
    try:
        summary = run_cycle(fetcher=fetcher, rules=rules, dedup=dedup, findings=findings)
    finally:
        dedup.close()
    cfg.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.heartbeat_path.write_text(datetime.now(timezone.utc).isoformat())
    logging.getLogger("inbox_watcher").info("run complete: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
