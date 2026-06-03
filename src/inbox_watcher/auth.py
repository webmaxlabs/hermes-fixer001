"""Sender-authentication gate. Pure functions over message metadata.

Real topology (confirmed against live forwarded mail, 2026-06-02): WebMax's alert
pipeline sends via Resend `from: alerts@webmaxlabs.com` `to: jake@webmaxlabs.com`;
the jake@ Google Workspace box forwards to `fixer001@agentmail.to`. So the trusted
SENDER is the first-party `webmaxlabs.com` domain (Resend/SES DKIM-signed), and the
RECIPIENT is the org domain (jake@/alerts@), NOT fixer001 directly. Vendor domains
are kept allowlisted for any future native vendor mail forwarded the same way.

Mail reaches us forwarded, so SPF fails in transit and is NOT used to reject. We
trust the forwarder-stamped Authentication-Results / ARC DKIM/DMARC verdict, a
from-domain allowlist, and a recipient-domain scope check (defense-in-depth: it
rejects mail addressed only to fixer001@, e.g. the Google forwarding confirmation).
"""
from __future__ import annotations
import re
from inbox_watcher.types import AuthVerdict

# From-domains we accept alerts from. webmaxlabs.com is the live first-party sender
# (Resend); the vendor domains cover future native vendor mail. Tune in one place.
ALLOWED_FROM_DOMAINS = frozenset({
    "webmaxlabs.com",
    "vercel.com",
    "stripe.com",
    "github.com",
    "supabase.com",
    "supabase.io",
})

# Mail must be addressed to our org (jake@ or alerts@ @webmaxlabs.com); this is the
# forwarding path. Mail addressed only to fixer001@agentmail.to is rejected.
REQUIRED_RECIPIENT_DOMAIN = "webmaxlabs.com"

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
    # 1. recipient scope (defense-in-depth; mail must reach our org domain, not
    #    fixer001@ directly).
    if not any(domain_of(a) == REQUIRED_RECIPIENT_DOMAIN for a in to_addrs):
        return AuthVerdict(ok=False, reason=f"no recipient on {REQUIRED_RECIPIENT_DOMAIN}")

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
