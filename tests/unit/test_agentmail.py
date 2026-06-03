# tests/unit/test_agentmail.py
from __future__ import annotations
from types import SimpleNamespace
from pathlib import Path
import pytest
from inbox_watcher.agentmail import AgentMailFetcher
from inbox_watcher.cursor import Cursor


def _msg(mid, frm, subj, ts, dkim="pass", to="alerts@webmaxlabs.com"):
    return SimpleNamespace(
        message_id=mid, from_=frm, to=[to], subject=subj, text="body "+subj,
        timestamp=ts,
        headers={"Authentication-Results": f"x; dkim={dkim} header.d={frm.split('@')[-1]}; dmarc={dkim} header.from={frm.split('@')[-1]}"},
    )


class FakeMessages:
    def __init__(self, listed, full):
        self._listed, self._full = listed, full
        self.list_calls = []
    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return SimpleNamespace(messages=self._listed, next_page_token=None)
    def get(self, *, inbox_id, message_id):
        return self._full[message_id]


class FakeClient:
    def __init__(self, listed, full):
        self.inboxes = SimpleNamespace(messages=FakeMessages(listed, full))


def _fetcher(tmp_path, listed, full):
    client = FakeClient(listed, full)
    cur = Cursor(tmp_path / "cursor.json")
    return AgentMailFetcher(client=client, inbox_id="fixer001@agentmail.to",
                            cursor=cur, allowed_domains=frozenset({"vercel.com"})), client


def test_yields_authenticated_message_and_advances_cursor(tmp_path: Path):
    full = {"m1": _msg("m1", "alerts@vercel.com", "Deploy failed", "2026-06-02T10:00:00+00:00")}
    f, _ = _fetcher(tmp_path, list(full.values()), full)
    out = list(f.fetch())
    assert len(out) == 1
    assert out[0].vendor == "vercel"
    assert out[0].message_id == "m1"
    assert f._cursor.last_ts() == "2026-06-02T10:00:00+00:00"


def test_quarantines_unauthenticated_sender(tmp_path: Path):
    full = {"m2": _msg("m2", "attacker@evil.com", "hi", "2026-06-02T10:00:00+00:00", dkim="pass")}
    f, _ = _fetcher(tmp_path, list(full.values()), full)
    assert list(f.fetch()) == []   # evil.com not in allowed_domains


def test_skips_messages_at_or_before_cursor(tmp_path: Path):
    cur = Cursor(tmp_path / "cursor.json"); cur.set("2026-06-02T10:00:00+00:00")
    full = {"old": _msg("old", "alerts@vercel.com", "old", "2026-06-02T09:00:00+00:00")}
    client = FakeClient(list(full.values()), full)
    f = AgentMailFetcher(client=client, inbox_id="i", cursor=cur,
                         allowed_domains=frozenset({"vercel.com"}))
    assert list(f.fetch()) == []
