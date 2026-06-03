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

        return cls(
            agentmail_api_key=req("AGENTMAIL_API_KEY"),
            inbox_id=os.environ.get("AGENTMAIL_INBOX_ID", "fixer001@agentmail.to").strip(),
            slack_bot_token=req("SLACK_BOT_TOKEN"),
            slack_channel=os.environ.get("SLACK_DIGEST_CHANNEL", "#hermes-digest").strip(),
            rules_path=REPO_ROOT / "config" / "rules.yaml",
            data_dir=Path(os.environ.get("INBOX_WATCHER_DATA_DIR", str(REPO_ROOT / "data"))),
            findings_dir=Path(os.environ.get("INBOX_WATCHER_FINDINGS_DIR", str(REPO_ROOT / "findings"))),
            heartbeat_path=Path(os.environ.get(
                "INBOX_WATCHER_HEARTBEAT_PATH", str(Path.home() / "inbox-watcher" / ".last-run"))),
        )
