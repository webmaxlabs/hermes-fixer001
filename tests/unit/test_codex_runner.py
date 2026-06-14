from pathlib import Path
from inbox_watcher.codex_runner import run_codex, CodexResult, codex_logged_in


class _P:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode; self.stdout = stdout; self.stderr = stderr


def test_codex_logged_in_true_on_exit0_and_authed_text():
    runner = lambda cmd, **kw: _P(0, "Logged in using ChatGPT\n")
    assert codex_logged_in("codex", runner=runner) is True


def test_codex_logged_in_false_on_nonzero():
    runner = lambda cmd, **kw: _P(1, "", "Not logged in")
    assert codex_logged_in("codex", runner=runner) is False


def test_codex_logged_in_false_when_exit0_but_text_says_not_logged_in():
    # defensive: trust the words over the exit code if they disagree
    runner = lambda cmd, **kw: _P(0, "Not logged in\n")
    assert codex_logged_in("codex", runner=runner) is False


def test_codex_logged_in_false_when_binary_missing():
    def boom(cmd, **kw): raise FileNotFoundError("codex not found")
    assert codex_logged_in("/bad/codex", runner=boom) is False


def test_codex_logged_in_invokes_login_status():
    seen = {}
    def runner(cmd, **kw): seen["cmd"] = cmd; return _P(0, "Logged in using ChatGPT")
    codex_logged_in("mycodex", runner=runner)
    assert seen["cmd"] == ["mycodex", "login", "status"]


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
    import subprocess
    assert calls["kw"]["stdin"] is subprocess.DEVNULL  # else codex blocks on inherited stdin


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


def test_run_codex_os_error_is_not_ok():
    def boom(cmd, **kw): raise FileNotFoundError("codex not found")
    res = run_codex(clone_dir=Path("/tmp/x"), prompt="p", timeout_sec=1,
                    codex_bin="/bad/path/codex", runner=boom)
    assert res.ok is False
    assert "codex error" in res.stderr
