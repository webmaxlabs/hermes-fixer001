"""AgentMail poller: list → paginate → auth-gate → normalize to InboxMessage."""
from __future__ import annotations
import logging
from typing import Iterator
from inbox_watcher.auth import authenticate, domain_of
from inbox_watcher.cursor import Cursor
from inbox_watcher.types import InboxMessage

log = logging.getLogger("inbox_watcher.agentmail")

# from-domain → short vendor id used as the dedup source and digest label.
_VENDOR_BY_DOMAIN = {
    "vercel.com": "vercel",
    "stripe.com": "stripe",
    "github.com": "github",
    "supabase.com": "supabase",
    "supabase.io": "supabase",
}


def _sender_addr(msg) -> str:
    # Task 1 spike confirms the attribute; `from` is a Python keyword so the SDK
    # exposes it as `from_`. Fall back defensively.
    return getattr(msg, "from_", None) or getattr(msg, "from", "") or ""


def _vendor(from_addr: str) -> str:
    return _VENDOR_BY_DOMAIN.get(domain_of(from_addr), "unknown")


class AgentMailFetcher:
    def __init__(self, *, client, inbox_id: str, cursor: Cursor,
                 allowed_domains: frozenset[str], page_limit: int = 50) -> None:
        self._client = client
        self._inbox = inbox_id
        self._cursor = cursor
        self._allowed = allowed_domains
        self._limit = page_limit

    def _iter_raw(self) -> Iterator[object]:
        token = None
        while True:
            kwargs = {"inbox_id": self._inbox, "limit": self._limit,
                      "include_unauthenticated": True, "ascending": True}
            if token:
                kwargs["page_token"] = token
            page = self._client.inboxes.messages.list(**kwargs)
            for stub in (getattr(page, "messages", None) or []):
                yield stub
            token = getattr(page, "next_page_token", None)
            if not token:
                return

    def fetch(self) -> Iterator[InboxMessage]:
        """Yield authenticated InboxMessages newer than the cursor.

        Side effect: advances the cursor when the generator is exhausted. Must be
        fully consumed for the cursor to advance.
        """
        floor = self._cursor.last_ts()
        max_ts = floor
        for stub in self._iter_raw():
            ts = str(getattr(stub, "timestamp", "") or "")
            # Lexicographic compare is correct only for same-offset (UTC)
            # ISO-8601 timestamps; see NOTES-agentmail.md reconciliation.
            if floor and ts and ts <= floor:
                continue
            mid = getattr(stub, "message_id", "")
            try:
                full = self._client.inboxes.messages.get(inbox_id=self._inbox, message_id=mid)
            except Exception as exc:                       # per-message isolation
                # Cursor is intentionally NOT advanced past a fetch error, so a
                # transient failure is retried on the next cycle.
                log.warning("get message %s failed: %s", mid, exc)
                continue
            from_addr = _sender_addr(full)
            to_addrs = [str(a) for a in (getattr(full, "to", None) or [])]
            verdict = authenticate(from_addr=from_addr, to_addrs=to_addrs,
                                   headers=getattr(full, "headers", None) or {},
                                   allowed_domains=self._allowed)
            if not verdict.ok:
                log.info("quarantine %s: %s", mid, verdict.reason)
                if ts > max_ts:
                    max_ts = ts
                continue
            subject = str(getattr(full, "subject", "") or "")
            text = str(getattr(full, "text", "") or "")[:4000]
            yield InboxMessage(
                message_id=mid, vendor=_vendor(from_addr), from_addr=from_addr,
                subject=subject, text=text, ts=ts,
                link=f"https://app.agentmail.to/inboxes/{self._inbox}/messages/{mid}",
                raw=f"{subject}\n{text[:500]}",
            )
            if ts > max_ts:
                max_ts = ts
        if max_ts:
            self._cursor.set(max_ts)
