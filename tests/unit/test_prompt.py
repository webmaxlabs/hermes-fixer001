from inbox_watcher.prompt import build_fixer_prompt


def test_prompt_uses_our_fields_only():
    p = build_fixer_prompt(repo="agent-intel-kit",
                           rule_description="database integrity/constraint error",
                           fix_hint="Make the write idempotent (upsert).")
    assert "agent-intel-kit" in p
    assert "database integrity/constraint error" in p
    assert "idempotent" in p
    assert "draft" in p.lower() or "minimal" in p.lower()


def test_prompt_excludes_email_text():
    # the function signature has no place for summary/subject/body.
    import inspect
    params = set(inspect.signature(build_fixer_prompt).parameters)
    assert params == {"repo", "rule_description", "fix_hint"}


def test_prompt_handles_missing_fix_hint():
    p = build_fixer_prompt(repo="r", rule_description="d", fix_hint=None)
    assert "r" in p and "d" in p
