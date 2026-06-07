"""Environment + path configuration."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Config:
    agentmail_api_key: str
    inbox_id: str
    slack_bot_token: str
    slack_channel: str
    rules_path: Path
    data_dir: Path
    findings_dir: Path
    heartbeat_path: Path
    dispatch_secret: str
    dispatch_mode: str
    repo_map_path: Path
    dispatch_ledger_path: Path
    codex_bin: str
    codex_timeout_sec: int
    github_token: str
    fixer_pr_labels: list[str]
    fixer_default_owner: str
    fixer_workdir: Path
    fixer_lock_path: Path

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Config":
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv(REPO_ROOT / ".env", override=False)

        def req(name: str) -> str:
            v = os.environ.get(name, "").strip()
            if not v:
                raise RuntimeError(f"missing required env var: {name}")
            return v

        findings_dir = Path(os.environ.get(
            "INBOX_WATCHER_FINDINGS_DIR", str(REPO_ROOT / "findings")))

        labels = [s.strip() for s in os.environ.get("FIXER_PR_LABELS", "hermes-fixer").split(",") if s.strip()]

        return cls(
            agentmail_api_key=req("AGENTMAIL_API_KEY"),
            inbox_id=os.environ.get("AGENTMAIL_INBOX_ID", "fixer001@agentmail.to").strip(),
            slack_bot_token=req("SLACK_BOT_TOKEN"),
            slack_channel=os.environ.get("SLACK_DIGEST_CHANNEL", "#hermes-digest").strip(),
            rules_path=REPO_ROOT / "config" / "rules.yaml",
            data_dir=Path(os.environ.get("INBOX_WATCHER_DATA_DIR", str(REPO_ROOT / "data"))),
            findings_dir=findings_dir,
            heartbeat_path=Path(os.environ.get(
                "INBOX_WATCHER_HEARTBEAT_PATH", str(Path.home() / "inbox-watcher" / ".last-run"))),
            dispatch_secret=os.environ.get("HERMES_FIXER_DISPATCH_SECRET", "").strip(),
            dispatch_mode=os.environ.get("DISPATCH_MODE", "dry_run").strip() or "dry_run",
            repo_map_path=REPO_ROOT / "config" / "repo_map.yaml",
            dispatch_ledger_path=findings_dir / "dispatched.jsonl",
            codex_bin=os.environ.get("CODEX_BIN", "codex").strip() or "codex",
            codex_timeout_sec=int(os.environ.get("CODEX_TIMEOUT_SEC", "600")),
            github_token=os.environ.get("GITHUB_TOKEN", "").strip(),
            fixer_pr_labels=labels or ["hermes-fixer"],
            fixer_default_owner=os.environ.get("FIXER_DEFAULT_OWNER", "webmaxlabs").strip() or "webmaxlabs",
            fixer_workdir=Path(os.environ.get("FIXER_WORKDIR", str(Path.home() / "inbox-watcher" / "fixer-work"))),
            fixer_lock_path=Path(os.environ.get("FIXER_LOCK_PATH", str(Path.home() / "inbox-watcher" / "fixer.lock"))),
        )
