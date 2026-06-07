from pathlib import Path
from inbox_watcher.gitops import clone, has_changes, commit_branch_push, repo_url


def _recorder():
    calls = []
    def runner(cmd, **kw):
        calls.append(cmd)
        class P: returncode = 0; stdout = ""; stderr = ""
        return P()
    return calls, runner


def test_repo_url():
    assert repo_url("webmaxlabs", "agent-intel-kit") == "https://github.com/webmaxlabs/agent-intel-kit.git"


def test_clone_runs_git_clone():
    calls, runner = _recorder()
    clone("https://github.com/o/r.git", Path("/tmp/d"), runner=runner)
    assert calls[0][:2] == ["git", "clone"]
    assert "/tmp/d" in calls[0]


def test_has_changes_true_when_porcelain_nonempty():
    def runner(cmd, **kw):
        class P: returncode = 0; stdout = " M file.py\n"; stderr = ""
        return P()
    assert has_changes(Path("/tmp/d"), runner=runner) is True


def test_has_changes_false_when_clean():
    def runner(cmd, **kw):
        class P: returncode = 0; stdout = ""; stderr = ""
        return P()
    assert has_changes(Path("/tmp/d"), runner=runner) is False


def test_commit_branch_push_sequence():
    calls, runner = _recorder()
    commit_branch_push(Path("/tmp/d"), branch="hermes-fixer/abc", message="fix", runner=runner)
    joined = [" ".join(c) for c in calls]
    assert any("checkout -b hermes-fixer/abc" in j for j in joined)
    assert any(j.startswith("git -C") and "add -A" in j for j in joined) or any("add -A" in j for j in joined)
    assert any("commit" in j for j in joined)
    assert any("push" in j for j in joined)
