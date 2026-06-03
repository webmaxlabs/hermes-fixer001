# tests/conftest.py
from __future__ import annotations
import os
import pytest


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("INBOX_WATCHER_") or key in {
            "AGENTMAIL_API_KEY", "AGENTMAIL_INBOX_ID",
            "SLACK_BOT_TOKEN", "SLACK_DIGEST_CHANNEL",
        }:
            monkeypatch.delenv(key, raising=False)
