"""Sender-authentication gate. Pure functions over message metadata.

Mail reaches us forwarded through Workspace, so SPF fails in transit and is NOT
used to reject. We trust the forwarder-stamped Authentication-Results / ARC
verdict (original vendor DKIM + DMARC), an explicit from-domain allowlist, and a
recipient-scope check.
"""
from __future__ import annotations
import re
from inbox_watcher.types import AuthVerdict

# Vendor domains we accept alerts from. Tune in one place.
ALLOWED_FROM_DOMAINS = frozenset({
    "vercel.com",
    "stripe.com",
    "github.com",
    "supabase.com",
    "supabase.io",
})

REQUIRED_RECIPIENT = "alerts@webmaxlabs.com"

_DKIM_RE = re.compile(r"\bdkim=(\w+)", re.I)
_DMARC_RE = re.compile(r"\bdmarc=(\w+)", re.I)


def _bare_addr(addr: str) -> str:
    # Extract bare "user@domain" from "Display Name <user@domain>" or "user@domain".
    m = re.search(r"<([^>]+)>", addr)
    return (m.group(1) if m else addr).strip().lower()


def domain_of(addr: str) -> str:
    return _bare_addr(addr).split("@")[-1]


def _auth_results(headers: dict) -> str:
    # Prefer Authentication-Results; fall back to the ARC chain.
    for key in ("Authentication-Results", "ARC-Authentication-Results"):
        for k, v in (headers or {}).items():
            if k.lower() == key.lower() and v:
                return v
    return ""


def authenticate(*, from_addr: str, to_addrs: list[str], headers: dict,
                 allowed_domains: frozenset[str]) -> AuthVerdict:
    # 1. recipient scope (defense-in-depth; the forward is alerts-only).
    if not any(_bare_addr(a) == REQUIRED_RECIPIENT for a in to_addrs):
        return AuthVerdict(ok=False, reason="recipient not alerts@webmaxlabs.com")

    # 2. from-domain allowlist.
    dom = domain_of(from_addr)
    if dom not in allowed_domains:
        return AuthVerdict(ok=False, reason=f"from domain not allowed: {dom}")

    # 3. DKIM/DMARC from the forwarder-stamped verdict (SPF intentionally ignored).
    ar = _auth_results(headers)
    if not ar:
        return AuthVerdict(ok=False, reason="no Authentication-Results header to verify auth")
    m_dkim = _DKIM_RE.search(ar)
    m_dmarc = _DMARC_RE.search(ar)
    dkim = m_dkim.group(1).lower() if m_dkim else ""
    dmarc = m_dmarc.group(1).lower() if m_dmarc else ""
    if dkim == "pass" or dmarc == "pass":
        return AuthVerdict(ok=True, reason="")
    return AuthVerdict(ok=False, reason=f"dkim={dkim or 'absent'} dmarc={dmarc or 'absent'} (neither passed)")
