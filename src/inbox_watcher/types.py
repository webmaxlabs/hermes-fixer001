"""Shared dataclasses for inbox-watcher."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuthVerdict:
    """Result of the sender-authentication gate."""
    ok: bool
    reason: str            # "" when ok; else why it was quarantined


@dataclass(frozen=True)
class InboxMessage:
    """A normalized, authenticated inbound email ready for classification."""
    message_id: str
    vendor: str            # short source id, e.g. "vercel" | "stripe" | "github" | "unknown"
    from_addr: str
    subject: str
    text: str              # plain-text body (may be truncated upstream)
    ts: str                # ISO-8601 UTC
    link: str              # AgentMail web link back to the message
    raw: str               # subject + body snippet used for hashing/classification


@dataclass(frozen=True)
class InboxFinding:
    """A classified inbox message after rules + dedup."""
    ts: str
    vendor: str
    priority: str          # P1 | P2 | P3
    rule_id: str           # matched rule id, or "unclassified"
    subject: str
    summary: str           # one-line human summary for the digest
    message_id: str
    link: str
    hash: str
    dedup_decision: str    # send | digest_only | suppress_dedup
    repo: str | None = None  # reserved for Spec 2 routing; always None in Spec 1
