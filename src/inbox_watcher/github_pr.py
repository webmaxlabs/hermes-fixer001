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


def _err_body(resp) -> str:
    try:
        return str(resp.json())
    except Exception:
        return resp.text


def find_open_pr_for_head(*, owner: str, repo: str, head: str, token: str,
                          http: Callable = _default_http) -> str | None:
    """Return the html_url of an OPEN PR whose head branch is `head`, else None.

    Idempotency guard for the fixer: if a prior run already opened a PR for this
    error (e.g. it crashed after open_draft_pr but before recording), the retry
    must recover that PR instead of opening a second one. Raises on a non-2xx so
    the caller fails closed (defers the fix) rather than risk a duplicate PR.
    """
    resp = http("GET", f"{_API}/repos/{owner}/{repo}/pulls",
                headers=_headers(token), timeout=30,
                params={"head": f"{owner}:{head}", "state": "open"})
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"PR lookup failed {resp.status_code}: {_err_body(resp)}")
    data = resp.json()
    return data[0]["html_url"] if data else None


def open_draft_pr(*, owner: str, repo: str, head: str, base: str, title: str, body: str,
                  labels: list[str], token: str, http: Callable = _default_http) -> str:
    resp = http("POST", f"{_API}/repos/{owner}/{repo}/pulls",
                headers=_headers(token), timeout=30,
                json={"title": title, "head": head, "base": base, "body": body, "draft": True})
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"PR create failed {resp.status_code}: {_err_body(resp)}")
    data = resp.json()
    number, url = data["number"], data["html_url"]
    if labels:
        lr = http("POST", f"{_API}/repos/{owner}/{repo}/issues/{number}/labels",
                  headers=_headers(token), timeout=30, json={"labels": labels})
        if lr.status_code not in (200, 201):
            log.warning("label add failed %s: %s", lr.status_code, _err_body(lr))
    log.info("opened draft PR #%s %s", number, url)
    return url


def _parse(pr_url: str) -> tuple[str, str, str]:
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)$", pr_url)
    if not m:
        raise ValueError(f"unparseable PR url: {pr_url}")
    return m.group(1), m.group(2), m.group(3)


def get_pr_state(pr_url: str, *, token: str, http: Callable = _default_http) -> str:
    owner, repo, number = _parse(pr_url)
    resp = http("GET", f"{_API}/repos/{owner}/{repo}/pulls/{number}",
                headers=_headers(token), timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"PR state fetch failed {resp.status_code}: {resp.text}")
    d = resp.json()
    if d.get("merged"):
        return "merged"
    return d.get("state", "unknown")  # "open" | "closed"
