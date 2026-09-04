from __future__ import annotations

import dns.exception
import dns.resolver

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.infrastructure.dns_prefilter import DnsPrefilter
from domain_finder.infrastructure.whois.checker import DomainChecker


class FakeResolver:
    def __init__(self, outcome) -> None:
        self.outcome = outcome

    def resolve(self, domain: str, record_type: str, lifetime: float):
        assert record_type == "NS"
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_ns_records_prove_registration() -> None:
    prefilter = DnsPrefilter(resolver=FakeResolver(["ns1.example."]))
    assert prefilter.has_nameservers("example.com") is True


def test_nxdomain_does_not_prove_availability() -> None:
    prefilter = DnsPrefilter(resolver=FakeResolver(dns.resolver.NXDOMAIN()))
    assert prefilter.has_nameservers("random.com") is False


def test_noanswer_continues_to_rdap() -> None:
    prefilter = DnsPrefilter(resolver=FakeResolver(dns.resolver.NoAnswer()))
    assert prefilter.has_nameservers("parked.com") is False


def test_dns_timeout_is_inconclusive() -> None:
    prefilter = DnsPrefilter(resolver=FakeResolver(dns.exception.Timeout()))
    assert prefilter.has_nameservers("example.com") is None


def test_nameserver_failure_is_inconclusive() -> None:
    prefilter = DnsPrefilter(resolver=FakeResolver(dns.resolver.NoNameservers()))
    assert prefilter.has_nameservers("example.com") is None


class FakePrefilter:
    def __init__(self, value: bool | None) -> None:
        self.value = value

    def has_nameservers(self, domain: str) -> bool | None:
        return self.value


class CountingRdap:
    def __init__(self) -> None:
        self.calls = 0

    def check_domain(self, domain: str) -> DomainCheckResult:
        self.calls += 1
        return DomainCheckResult(
            domain=domain, status=DomainCheckStatus.AVAILABLE, source="rdap", checked_at=1.0
        )


def test_checker_skips_rdap_only_when_dns_proves_registration() -> None:
    checker = DomainChecker(dns_prefilter=True, whois_fallback=False)
    rdap = CountingRdap()
    checker.rdap_client = rdap
    checker.dns_prefilter = FakePrefilter(True)

    result = checker.check_domain("example.com")
    assert result.status is DomainCheckStatus.REGISTERED
    assert result.source == "dns"
    assert rdap.calls == 0


def test_checker_uses_rdap_when_dns_has_no_proof() -> None:
    checker = DomainChecker(dns_prefilter=True, whois_fallback=False)
    rdap = CountingRdap()
    checker.rdap_client = rdap
    checker.dns_prefilter = FakePrefilter(False)

    result = checker.check_domain("random.com")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert rdap.calls == 1
