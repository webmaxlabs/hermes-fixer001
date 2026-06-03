import re
import pytest
from inbox_watcher.repo_resolver import (
    ALLOWLIST, RepoMap, load_repo_map, resolve_repo, make_resolver,
)

MAP_YAML = """
extractors:
  vercel: '(?i)project[:/ ]+(?P<project>[a-z0-9][a-z0-9-]{0,99})'
  github: '(?i)github\\.com/[^/\\s]+/(?P<project>[a-z0-9][a-z0-9._-]{0,99})'
mappings:
  - vendor: vercel
    project: nexus-prod
    repo: nexus-uncensored
  - vendor: github
    project: boe-generator
    repo: boe-generator
"""


@pytest.fixture
def repo_map(tmp_path):
    p = tmp_path / "repo_map.yaml"
    p.write_text(MAP_YAML)
    return load_repo_map(p)


def test_resolves_mapped_project(repo_map):
    assert resolve_repo("vercel", "Project: nexus-prod failed to deploy", repo_map) == "nexus-uncensored"


def test_extractor_miss_returns_none(repo_map):
    assert resolve_repo("vercel", "no project identifier here", repo_map) is None


def test_unmapped_project_returns_none(repo_map):
    # extracted fine, but 'whatever' is not in the map
    assert resolve_repo("vercel", "Project: whatever broke", repo_map) is None


def test_vendor_mismatch_returns_none(repo_map):
    # 'nexus-prod' only maps under vendor 'vercel', not 'github'
    assert resolve_repo("github", "Project: nexus-prod", repo_map) is None


def test_injection_attempt_cannot_introduce_new_repo(repo_map):
    # Attacker-controlled body names a repo that is NOT in the map.
    assert resolve_repo("vercel", "Project: evil-repo deploy for nexus-uncensored", repo_map) is None


def test_resolved_repo_always_in_allowlist(repo_map):
    repo = resolve_repo("github", "see https://github.com/webmaxlabs/boe-generator/runs/1", repo_map)
    assert repo == "boe-generator"
    assert repo in ALLOWLIST


def test_make_resolver_closes_over_map(repo_map):
    resolver = make_resolver(repo_map)
    assert resolver("vercel", "Project: nexus-prod") == "nexus-uncensored"
    assert resolver("vercel", "unrelated") is None


def test_invalid_regex_raises(tmp_path):
    p = tmp_path / "repo_map.yaml"
    p.write_text("extractors:\n  vercel: '(?P<project>[unterminated'\n")
    with pytest.raises(ValueError):
        load_repo_map(p)


def test_extractor_without_project_group_raises(tmp_path):
    p = tmp_path / "repo_map.yaml"
    p.write_text("extractors:\n  vercel: 'project[:/ ]+([a-z0-9-]+)'\n")
    with pytest.raises(ValueError):
        load_repo_map(p)


def test_mapping_repo_not_in_allowlist_raises(tmp_path):
    p = tmp_path / "repo_map.yaml"
    p.write_text(
        "mappings:\n"
        "  - vendor: vercel\n"
        "    project: nexus-prod\n"
        "    repo: not-allowlisted\n"
    )
    with pytest.raises(ValueError):
        load_repo_map(p)


def test_mapping_missing_field_raises(tmp_path):
    p = tmp_path / "repo_map.yaml"
    p.write_text(
        "mappings:\n"
        "  - vendor: vercel\n"
        "    project: nexus-prod\n"
    )
    with pytest.raises(ValueError):
        load_repo_map(p)


def test_nonexistent_path_returns_empty_map(tmp_path):
    p = tmp_path / "does_not_exist.yaml"
    rm = load_repo_map(p)
    assert isinstance(rm, RepoMap)
    assert dict(rm.mappings) == {}
    assert dict(rm.extractors) == {}
