"""Open draft PRs + read PR state via the GitHub REST API (no gh CLI needed)."""
from __future__ import annotations
import logging
import re
from typing import Callable
import httpx

log = logging.getLogger("inbox_watcher.github_pr")
_API = "https://api.github.com"


def _default_http(method: str, url: str, **kw):
    return httpx.request(method, url, **kw)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def open_draft_pr(*, owner: str, repo: str, head: str, base: str, title: str, body: str,
                  labels: list[str], token: str, http: Callable = _default_http) -> str:
    resp = http("POST", f"{_API}/repos/{owner}/{repo}/pulls",
                headers=_headers(token), timeout=30,
                json={"title": title, "head": head, "base": base, "body": body, "draft": True})
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"PR create failed {resp.status_code}: {resp.json()}")
    data = resp.json()
    number, url = data["number"], data["html_url"]
    if labels:
        lr = http("POST", f"{_API}/repos/{owner}/{repo}/issues/{number}/labels",
                  headers=_headers(token), timeout=30, json={"labels": labels})
        if lr.status_code not in (200, 201):
            log.warning("label add failed %s: %s", lr.status_code, lr.json())
    return url


def _parse(pr_url: str) -> tuple[str, str, str]:
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        raise ValueError(f"unparseable PR url: {pr_url}")
    return m.group(1), m.group(2), m.group(3)


def get_pr_state(pr_url: str, *, token: str, http: Callable = _default_http) -> str:
    owner, repo, number = _parse(pr_url)
    resp = http("GET", f"{_API}/repos/{owner}/{repo}/pulls/{number}",
                headers=_headers(token), timeout=30)
    d = resp.json()
    if d.get("merged"):
        return "merged"
    return d.get("state", "unknown")  # "open" | "closed"
