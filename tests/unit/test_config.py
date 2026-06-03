# tests/unit/test_config.py
from __future__ import annotations
import pytest
from inbox_watcher.config import Config


def test_load_requires_agentmail_key(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    with pytest.raises(RuntimeError, match="AGENTMAIL_API_KEY"):
        Config.load()


def test_load_reads_defaults(monkeypatch):
    monkeypatch.setenv("AGENTMAIL_API_KEY", "k")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "t")
    cfg = Config.load()
    assert cfg.agentmail_api_key == "k"
    assert cfg.inbox_id == "fixer001@agentmail.to"
    assert cfg.slack_channel == "#hermes-digest"
    assert cfg.rules_path.name == "rules.yaml"
