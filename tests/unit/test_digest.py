# tests/unit/test_digest.py
from __future__ import annotations
from inbox_watcher.digest import build_digest_text, dedupe_rank


def _row(h, prio, vendor, subject, link="https://x", decision="digest_only"):
    return {"hash": h, "priority": prio, "vendor": vendor, "subject": subject,
            "summary": f"{vendor}: {subject}", "link": link, "dedup_decision": decision}


def test_dedupe_rank_orders_p1_first_and_drops_suppressed_dupes():
    rows = [
        _row("a", "P3", "github", "digest"),
        _row("b", "P1", "vercel", "deploy failed"),
        _row("b", "P1", "vercel", "deploy failed", decision="suppress_dedup"),
        _row("c", "P2", "stripe", "dispute"),
    ]
    ranked = dedupe_rank(rows)
    assert [r["hash"] for r in ranked] == ["b", "c", "a"]   # P1, P2, P3; b deduped to one


def test_build_text_groups_by_priority_and_includes_links():
    rows = [_row("b", "P1", "vercel", "deploy failed", link="https://app.agentmail.to/b")]
    text = build_digest_text(dedupe_rank(rows), run_date="2026-06-02")
    assert "P1" in text and "vercel" in text
    assert "https://app.agentmail.to/b" in text


def test_build_text_handles_empty():
    text = build_digest_text([], run_date="2026-06-02")
    assert "No new" in text


def test_post_digest_calls_poster(mocker):
    from inbox_watcher import digest
    posted = {}
    def fake_post(channel, text):
        posted["channel"], posted["text"] = channel, text
        return True
    ok = digest.post_digest([_row("b", "P1", "vercel", "deploy failed")],
                            run_date="2026-06-02", channel="#hermes-digest", poster=fake_post)
    assert ok is True
    assert posted["channel"] == "#hermes-digest"
    assert "P1" in posted["text"]
