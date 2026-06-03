# tests/unit/test_auth.py
from __future__ import annotations
from inbox_watcher.auth import authenticate, ALLOWED_FROM_DOMAINS

OK_HEADERS = {"Authentication-Results": "mx.google.com; dkim=pass header.d=vercel.com; spf=fail; dmarc=pass header.from=vercel.com"}


def test_passes_when_dkim_and_dmarc_pass_and_domain_allowed():
    v = authenticate(from_addr="alerts@vercel.com", to_addrs=["alerts@webmaxlabs.com"],
                     headers=OK_HEADERS, allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is True
    assert v.reason == ""


def test_spf_fail_alone_does_not_quarantine():
    # SPF fail is expected for forwarded mail; DKIM+DMARC pass is sufficient.
    v = authenticate(from_addr="alerts@vercel.com", to_addrs=["alerts@webmaxlabs.com"],
                     headers=OK_HEADERS, allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is True


def test_quarantines_unknown_from_domain():
    v = authenticate(from_addr="attacker@evil.com", to_addrs=["alerts@webmaxlabs.com"],
                     headers={"Authentication-Results": "x; dkim=pass header.d=evil.com; dmarc=pass header.from=evil.com"},
                     allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is False
    assert "domain" in v.reason


def test_quarantines_when_dkim_fails():
    v = authenticate(from_addr="alerts@vercel.com", to_addrs=["alerts@webmaxlabs.com"],
                     headers={"Authentication-Results": "x; dkim=fail header.d=vercel.com; dmarc=fail"},
                     allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is False
    assert "dkim" in v.reason.lower() or "dmarc" in v.reason.lower()


def test_quarantines_when_recipient_not_alerts():
    v = authenticate(from_addr="alerts@vercel.com", to_addrs=["jake@webmaxlabs.com"],
                     headers=OK_HEADERS, allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is False
    assert "recipient" in v.reason


def test_quarantines_when_no_auth_results_header():
    v = authenticate(from_addr="alerts@vercel.com", to_addrs=["alerts@webmaxlabs.com"],
                     headers={}, allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is False
    assert "auth" in v.reason.lower()


def test_dmarc_pass_with_dkim_absent_but_arc_present():
    # Some forwarders stamp the original verdict in ARC-Authentication-Results.
    v = authenticate(from_addr="receipts@stripe.com", to_addrs=["alerts@webmaxlabs.com"],
                     headers={"ARC-Authentication-Results": "i=1; mx.google.com; dkim=pass header.d=stripe.com; dmarc=pass header.from=stripe.com"},
                     allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is True


def test_recipient_substring_spoof_is_quarantined():
    v = authenticate(from_addr="alerts@vercel.com",
                     to_addrs=["alerts@webmaxlabs.com <fixer001@agentmail.to>"],
                     headers=OK_HEADERS, allowed_domains=ALLOWED_FROM_DOMAINS)
    assert v.ok is False
    assert "recipient" in v.reason
