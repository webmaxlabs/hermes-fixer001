"""Run the local Codex CLI non-interactively against a clone.

NB: the exact `codex exec` flags depend on the installed Codex version; B2 verifies
them on agent001. The sandbox is workspace-write confined to clone_dir, approvals off.
"""
from __future__ import annotations
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("inbox_watcher.codex_runner")


@dataclass(frozen=True)
class CodexResult:
    ok: bool
    stdout: str
    stderr: str


def run_codex(*, clone_dir: Path, prompt: str, timeout_sec: int,
              codex_bin: str = "codex", runner: Callable = subprocess.run) -> CodexResult:
    cmd = [codex_bin, "exec", "--sandbox", "workspace-write",
           "--skip-git-repo-check", prompt]
    try:
        proc = runner(cmd, cwd=str(clone_dir), capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        log.warning("codex timed out after %ss in %s", timeout_sec, clone_dir)
        return CodexResult(False, "", f"codex timeout after {timeout_sec}s")
    except Exception as exc:
        return CodexResult(False, "", f"codex error: {exc}")
    ok = proc.returncode == 0
    return CodexResult(ok, proc.stdout or "", proc.stderr or "")
