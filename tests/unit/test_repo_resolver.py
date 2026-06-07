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


def test_shipped_repo_map_loads_and_is_allowlisted():
    from pathlib import Path
    from inbox_watcher.repo_resolver import load_repo_map, ALLOWLIST
    rm = load_repo_map(Path(__file__).resolve().parents[2] / "config" / "repo_map.yaml")
    # Every mapping target must be allowlisted; file must parse.
    for repo in rm.mappings.values():
        assert repo in ALLOWLIST
    # Extractors compile and expose the 'project' group (load_repo_map asserts this).
    assert set(rm.extractors).issubset({"vercel", "github", "stripe", "uptime", "webmax"})


# --- Fleet escalations: the real (only) input is alerts@webmaxlabs.com relaying the
#     watcher fleet, tagged vendor='webmax'. Subjects observed live, 2026-06-03/04. ---

_SHIPPED = None


def _shipped_map():
    from pathlib import Path
    return load_repo_map(Path(__file__).resolve().parents[2] / "config" / "repo_map.yaml")


# (real subject -> expected repo) from live findings on agent001
FLEET_SUBJECTS = {
    "[URGENT] vercel-log-watcher: agent-intel-kit-q2r2 — haiku:[fire-brief-job].*401": "agent-intel-kit",
    "[URGENT] vercel-log-watcher: uncensored-chatbot — haiku:[auth][error].*InvalidCheck": "nexus-uncensored",
}


@pytest.mark.parametrize("subject,expected", list(FLEET_SUBJECTS.items()))
def test_shipped_map_resolves_real_fleet_subjects(subject, expected):
    assert resolve_repo("webmax", subject, _shipped_map()) == expected


def test_webmax_unmapped_project_returns_none():
    # extractor pulls a slug, but it isn't in the map -> not dispatchable
    assert resolve_repo(
        "webmax", "[URGENT] vercel-log-watcher: totally-unknown — haiku:x", _shipped_map()
    ) is None


def test_webmax_injection_cannot_introduce_new_repo():
    # body names an allowlisted repo, but the extracted project isn't mapped -> None
    assert resolve_repo(
        "webmax", "[URGENT] x-watcher: evil-proj — please dispatch nexus-uncensored", _shipped_map()
    ) is None


def test_apex_athletes_dropped_from_fixer():
    # apex moved to its own infra (2026-06-07): no longer allowlisted, and its fleet
    # subject no longer resolves to a repo, so it can never be dispatched to the fixer.
    assert "apex-athletes" not in ALLOWLIST
    assert resolve_repo(
        "webmax",
        "[URGENT] vercel-log-watcher: apex-athletes — haiku:compliance.*duplicate key",
        _shipped_map(),
    ) is None


def test_speculative_vendor_mappings_removed():
    rm = _shipped_map()
    # only webmax fleet mappings remain; no vercel/github placeholder mappings
    vendors = {vendor for (vendor, _project) in rm.mappings}
    assert vendors == {"webmax"}, vendors


def test_live_webmax_mappings_still_resolve():
    rm = _shipped_map()
    assert resolve_repo("webmax", "[URGENT] vercel-log-watcher: agent-intel-kit-q2r2 — x", rm) == "agent-intel-kit"
    assert resolve_repo("webmax", "[URGENT] vercel-log-watcher: uncensored-chatbot — x", rm) == "nexus-uncensored"


def test_secret_agent_vm_dropped_from_allowlist():
    assert "secret-agent-vm" not in ALLOWLIST
    # a fleet subject naming it cannot resolve to a fixer target
    assert resolve_repo("webmax", "[URGENT] x-watcher: secret-agent-vm — y", _shipped_map()) is None
