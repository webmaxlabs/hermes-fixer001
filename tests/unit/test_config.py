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


def test_config_loads_dispatch_settings(tmp_path, monkeypatch):
    from inbox_watcher.config import Config
    # Clear any leaked dispatch env vars so load_dotenv (no override) picks up the file values
    monkeypatch.delenv("HERMES_FIXER_DISPATCH_SECRET", raising=False)
    monkeypatch.delenv("DISPATCH_MODE", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "AGENTMAIL_API_KEY=k\nSLACK_BOT_TOKEN=xoxb-t\n"
        "HERMES_FIXER_DISPATCH_SECRET=s3cret\nDISPATCH_MODE=dry_run\n"
    )
    cfg = Config.load(env_file=env)
    assert cfg.dispatch_secret == "s3cret"
    assert cfg.dispatch_mode == "dry_run"
    assert cfg.repo_map_path.name == "repo_map.yaml"
    assert cfg.dispatch_ledger_path.name == "dispatched.jsonl"


def test_config_dispatch_mode_defaults_dry_run(tmp_path, monkeypatch):
    from inbox_watcher.config import Config
    # Clear any leaked dispatch env vars so defaults are used
    monkeypatch.delenv("HERMES_FIXER_DISPATCH_SECRET", raising=False)
    monkeypatch.delenv("DISPATCH_MODE", raising=False)
    env = tmp_path / ".env"
    env.write_text("AGENTMAIL_API_KEY=k\nSLACK_BOT_TOKEN=xoxb-t\n")
    cfg = Config.load(env_file=env)
    assert cfg.dispatch_mode == "dry_run"
    assert cfg.dispatch_secret == ""
