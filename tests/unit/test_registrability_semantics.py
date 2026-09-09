from __future__ import annotations

import time

import httpx

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.infrastructure.whois.rdap_client import RdapClient
from domain_finder.infrastructure.whois.whois_evidence import classify_whois_text


class StaticBootstrap:
    def get_base_urls_for_domain(self, domain: str) -> tuple[str, ...]:
        return ("https://registry.test/",)


def _rdap(status: int, *, json_body=None, text: str = "") -> DomainCheckResult:
    def handler(_request: httpx.Request) -> httpx.Response:
        if json_body is not None:
            return httpx.Response(status, json=json_body)
        return httpx.Response(status, text=text)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = RdapClient(http_client=http, bootstrap=StaticBootstrap(), max_retries=1)
    return client.check_domain("candidate.com")


def test_unregistered_is_not_claimed_registrable() -> None:
    result = DomainCheckResult(
        domain="candidate.com",
        status=DomainCheckStatus.UNREGISTERED,
        source="rdap",
        checked_at=time.time(),
    )
    assert result.available is None
    assert result.is_unregistered is True
    assert result.is_registrable is False


def test_registrable_is_the_only_positive_purchase_signal() -> None:
    result = DomainCheckResult(
        domain="candidate.test",
        status=DomainCheckStatus.REGISTRABLE,
        source="whois",
        checked_at=time.time(),
    )
    assert result.available is True
    assert result.is_registrable is True
    assert result.is_unregistered is True


def test_rdap_404_means_unregistered_not_registrable() -> None:
    result = _rdap(404, json_body={"errorCode": 404, "title": "Not Found"})
    assert result.status is DomainCheckStatus.UNREGISTERED
    assert result.available is None


def test_rdap_explicit_reserved_response_is_reserved() -> None:
    result = _rdap(
        404,
        json_body={
            "errorCode": 404,
            "title": "Reserved",
            "description": ["not available for registration"],
        },
    )
    assert result.status is DomainCheckStatus.RESERVED
    assert result.available is False


def test_whois_absence_and_registrability_are_distinct() -> None:
    absent = classify_whois_text("candidate.com", 'No match for "CANDIDATE.COM".')
    purchasable = classify_whois_text(
        "candidate.test", "Domain candidate.test is available for registration"
    )
    assert absent is not None
    assert absent.status is DomainCheckStatus.UNREGISTERED
    assert purchasable is not None
    assert purchasable.status is DomainCheckStatus.REGISTRABLE


class FakeReservedPolicy:
    def match(self, domain: str):
        from domain_finder.infrastructure.whois.reserved_policy import ReservedNameMatch

        if domain == "reserved.com":
            return ReservedNameMatch("test-policy", "reserved by policy")
        return None


def test_checker_policy_overrides_registry_absence() -> None:
    from domain_finder.infrastructure.whois.checker import DomainChecker

    checker = DomainChecker(
        whois_fallback=False,
        dns_fallback=False,
        reserved_policy=FakeReservedPolicy(),
    )
    try:
        checker.rdap_client = type(
            "FakeRdap",
            (),
            {
                "check_domain": lambda _self, domain: DomainCheckResult(
                    domain=domain,
                    status=DomainCheckStatus.UNREGISTERED,
                    source="rdap",
                    checked_at=1.0,
                ),
                "get_rdap_host": lambda _self, _domain: None,
            },
        )()
        result = checker.check_domain("reserved.com")
    finally:
        checker.close()

    assert result.status is DomainCheckStatus.RESERVED
    assert result.source == "policy"
    assert result.available is False
