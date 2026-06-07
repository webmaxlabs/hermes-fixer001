from pathlib import Path
from inbox_watcher.codex_runner import run_codex, CodexResult


def test_run_codex_builds_command_and_reports_ok():
    calls = {}
    class P:
        returncode = 0; stdout = "done"; stderr = ""
    def fake_runner(cmd, **kw):
        calls["cmd"] = cmd; calls["kw"] = kw; return P()
    res = run_codex(clone_dir=Path("/tmp/x"), prompt="fix it",
                    timeout_sec=300, codex_bin="codex", runner=fake_runner)
    assert isinstance(res, CodexResult) and res.ok is True
    assert calls["cmd"][0] == "codex" and "exec" in calls["cmd"]
    assert "fix it" in calls["cmd"]
    assert calls["kw"]["timeout"] == 300
    assert calls["kw"]["cwd"] == "/tmp/x"


def test_run_codex_timeout_is_not_ok():
    import subprocess
    def boom(cmd, **kw): raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    res = run_codex(clone_dir=Path("/tmp/x"), prompt="p", timeout_sec=1,
                    codex_bin="codex", runner=boom)
    assert res.ok is False and "timeout" in res.stderr.lower()


def test_run_codex_nonzero_is_not_ok():
    class P:
        returncode = 1; stdout = ""; stderr = "boom"
    res = run_codex(clone_dir=Path("/tmp/x"), prompt="p", timeout_sec=1,
                    codex_bin="codex", runner=lambda c, **k: P())
    assert res.ok is False and res.stderr == "boom"
