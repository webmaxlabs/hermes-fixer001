"""Minimal git helpers over HTTPS (credentials supplied by ~/.netrc)."""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Callable


def repo_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}.git"


def _git(args: list[str], *, runner: Callable, cwd: str | None = None) -> subprocess.CompletedProcess:
    proc = runner(["git", *args] if cwd is None else ["git", "-C", cwd, *args],
                  capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def clone(url: str, dest: Path, *, depth: int = 1, runner: Callable = subprocess.run) -> None:
    _git(["clone", "--depth", str(depth), url, str(dest)], runner=runner)


def has_changes(repo_dir: Path, *, runner: Callable = subprocess.run) -> bool:
    proc = _git(["status", "--porcelain"], runner=runner, cwd=str(repo_dir))
    return bool((proc.stdout or "").strip())


def commit_branch_push(repo_dir: Path, *, branch: str, message: str,
                       runner: Callable = subprocess.run) -> None:
    d = str(repo_dir)
    _git(["checkout", "-b", branch], runner=runner, cwd=d)
    _git(["add", "-A"], runner=runner, cwd=d)
    # email must map to the webmaxlabs GitHub account or Vercel's deployment protection
    # blocks the PR's deploy ("commit email could not be matched to a GitHub account").
    _git(["-c", "user.name=hermes-fixer", "-c", "user.email=github@webmaxlabs.com",
          "commit", "-m", message], runner=runner, cwd=d)
    # --force: the branch name is deterministic + fixer-owned (hermes-fixer/<sig>), so a
    # retry legitimately overwrites a prior orphaned attempt (push ok, PR-create failed).
    _git(["push", "-u", "--force", "origin", branch], runner=runner, cwd=d)
