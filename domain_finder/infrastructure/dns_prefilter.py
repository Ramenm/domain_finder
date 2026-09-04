"""Safe DNS prefilter used only to prove that a domain is registered."""

from __future__ import annotations

import dns.exception
import dns.resolver


class DnsPrefilter:
    """Look for NS records without treating their absence as availability."""

    def __init__(self, timeout: float = 1.5, resolver=None) -> None:
        self.timeout = timeout
        self.resolver = resolver or dns.resolver.Resolver()

    def has_nameservers(self, domain: str) -> bool | None:
        """Return True for NS proof, False for no NS, None for DNS failure."""
        try:
            answer = self.resolver.resolve(domain, "NS", lifetime=self.timeout)
            return bool(answer)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return False
        except (
            dns.exception.Timeout,
            dns.resolver.NoNameservers,
            dns.exception.DNSException,
            OSError,
        ):
            return None
