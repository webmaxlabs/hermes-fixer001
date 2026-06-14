"""Resolve a finding to an allowlisted repo.

SECURITY GATE: the static map is the only authority. An extractor may read the
(untrusted) email body, but the resolved repo value comes from OUR config, never
from the email's text. Email can only SELECT among repos we pre-authorized; it can
never name a new one. Vendor must also match the mapping's vendor (defense in depth).
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping
import yaml

log = logging.getLogger("inbox_watcher.repo_resolver")

# The only repos the fixer may ever target. A mapping resolving outside this set is dropped.
ALLOWLIST = frozenset({
    "uncensored-chatbot", "agent-intel-kit", "boe-generator",
    # added 2026-06-13 (Jake expanded fixer scope to these revenue apps):
    "webmax-realtors", "grantsfast-www-app-v1", "secret-agent-v1",
    # "uncensored-chatbot" is the real GitHub repo; "nexus-uncensored" was an internal
    # codename that does not exist as a repo (fixed 2026-06-13, was crashing ingest).
    # apex-athletes dropped 2026-06-07 — apex moved to its own infra (own
    # Vercel/Supabase/Resend/GitHub, no longer under webmaxlabs), so it is no longer
    # a valid fixer target. Its alerts still arrive but now resolve repo=None.
})


@dataclass(frozen=True)
class RepoMap:
    mappings: Mapping[tuple[str, str], str]   # (vendor, project_id) -> repo
    extractors: Mapping[str, re.Pattern]      # vendor -> regex with named group 'project'


def load_repo_map(path: Path) -> RepoMap:
    if not path.exists():
        log.warning("repo_map not found at %s; resolver will return None for all", path)
        return RepoMap(mappings=MappingProxyType({}), extractors=MappingProxyType({}))
    data = yaml.safe_load(path.read_text()) or {}
    extractors: dict[str, re.Pattern] = {}
    for vendor, pat in (data.get("extractors") or {}).items():
        try:
            compiled = re.compile(pat)
        except re.error as exc:
            raise ValueError(f"bad extractor regex for vendor {vendor!r}: {exc}") from exc
        if "project" not in compiled.groupindex:
            raise ValueError(f"extractor for vendor {vendor!r} lacks a named group 'project'")
        extractors[vendor] = compiled
    mappings: dict[tuple[str, str], str] = {}
    for m in (data.get("mappings") or []):
        vendor = str(m.get("vendor", "")).strip()
        project = str(m.get("project", "")).strip().lower()
        repo = str(m.get("repo", "")).strip()
        if not (vendor and project and repo):
            raise ValueError(f"mapping missing vendor/project/repo: {m!r}")
        if repo not in ALLOWLIST:
            raise ValueError(f"mapping repo {repo!r} not in allowlist")
        mappings[(vendor, project)] = repo
    return RepoMap(
        mappings=MappingProxyType(mappings),
        extractors=MappingProxyType(extractors),
    )


def resolve_repo(vendor: str, text: str, repo_map: RepoMap) -> str | None:
    extractor = repo_map.extractors.get(vendor)
    if extractor is None:
        return None
    match = extractor.search(text or "")
    if not match:
        return None
    project = match.group("project").lower()
    repo = repo_map.mappings.get((vendor, project))
    if repo is None or repo not in ALLOWLIST:   # allowlist re-check (defense in depth)
        return None
    return repo


def make_resolver(repo_map: RepoMap) -> Callable[[str, str], str | None]:
    def resolver(vendor: str, text: str) -> str | None:
        return resolve_repo(vendor, text, repo_map)
    return resolver
