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


def test_main_builds_resolver_from_repo_map(tmp_path, monkeypatch):
    """main() calls make_resolver once and passes its result to run_cycle."""
    import inbox_watcher.__main__ as entrypoint

    # --- env: point all dirs at tmp_path so no real filesystem escapes ---
    monkeypatch.setenv("AGENTMAIL_API_KEY", "test-key")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("INBOX_WATCHER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INBOX_WATCHER_FINDINGS_DIR", str(tmp_path / "findings"))
    monkeypatch.setenv("INBOX_WATCHER_HEARTBEAT_PATH", str(tmp_path / "heartbeat"))
    (tmp_path / "data").mkdir()
    (tmp_path / "findings").mkdir()

    # --- stub make_resolver: record call, return a no-op resolver ---
    resolver_calls = []
    dummy_resolver = lambda vendor, text: None

    def fake_make_resolver(repo_map):
        resolver_calls.append(repo_map)
        return dummy_resolver

    monkeypatch.setattr(entrypoint, "make_resolver", fake_make_resolver)

    # --- stub network/IO objects so main() runs end-to-end without real calls ---
    class FakeClient:
        pass

    class FakeCursor:
        def __init__(self, *a, **kw):
            pass

    class FakeFetcher:
        def __init__(self, *a, **kw):
            pass
        def fetch(self):
            return iter([])

    class FakeDedup:
        def __init__(self, *a, **kw):
            pass
        def cleanup(self, **kw):
            return 0
        def close(self):
            pass

    monkeypatch.setattr(entrypoint, "AgentMail", lambda **kw: FakeClient())
    monkeypatch.setattr(entrypoint, "Cursor", FakeCursor)
    monkeypatch.setattr(entrypoint, "AgentMailFetcher", FakeFetcher)
    monkeypatch.setattr(entrypoint, "DedupStore", FakeDedup)

    result = entrypoint.main()

    assert result == 0
    assert len(resolver_calls) == 1, "make_resolver should be called exactly once"


def test_fixer_config_defaults(tmp_path, monkeypatch):
    for v in ("CODEX_BIN", "CODEX_TIMEOUT_SEC", "GITHUB_TOKEN", "FIXER_PR_LABELS", "FIXER_DEFAULT_OWNER"):
        monkeypatch.delenv(v, raising=False)
    env = tmp_path / ".env"
    env.write_text("AGENTMAIL_API_KEY=k\nSLACK_BOT_TOKEN=t\nHERMES_FIXER_DISPATCH_SECRET=s\n")
    cfg = __import__("inbox_watcher.config", fromlist=["Config"]).Config.load(env_file=env)
    assert cfg.codex_bin == "codex"
    assert cfg.codex_timeout_sec == 600
    assert cfg.fixer_default_owner == "webmaxlabs"
    assert cfg.fixer_pr_labels == ["hermes-fixer"]
    assert cfg.github_token == ""            # optional; only required in live
    assert cfg.fixer_lock_path.name == "fixer.lock"
