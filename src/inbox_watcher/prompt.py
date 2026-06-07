"""Build the Codex fixer prompt from OUR controlled fields only.

INJECTION BOUNDARY: this function takes no email-derived input (no subject, summary,
body, or sender). The only inputs are the allowlisted repo and the rule's own
description + fix_hint, both authored by us in rules.yaml. Do not add email fields.
"""
from __future__ import annotations


def build_fixer_prompt(*, repo: str, rule_description: str, fix_hint: str | None) -> str:
    hint = f"\nSuggested approach: {fix_hint}" if fix_hint else ""
    return (
        f"A monitored production error of class \"{rule_description}\" was reported "
        f"for the repository \"{repo}\".{hint}\n\n"
        "Investigate the codebase, find the root cause, and make the smallest "
        "correct change that fixes it. Keep the diff minimal and focused.\n\n"
        "If the problem is NOT addressable by a code change (for example a rotated "
        "secret, an environment/config issue, or missing infrastructure), make NO "
        "changes at all and briefly explain why in your final message. Do not invent "
        "a fix. A human will review your changes as a draft pull request before merge."
    )
