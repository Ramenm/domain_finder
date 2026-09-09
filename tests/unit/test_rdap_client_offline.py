from __future__ import annotations

import httpx
import pytest

from domain_finder.domain.models import DomainCheckStatus
from domain_finder.infrastructure.whois.rdap_client import RdapClient


class StaticBootstrap:
    def __init__(self, urls: tuple[str, ...] | None = ("https://registry.test/",)) -> None:
        self.urls = urls

    def get_base_urls_for_domain(self, domain: str) -> tuple[str, ...] | None:
        return self.urls


def make_client(handler, *, retries: int = 1, urls=("https://registry.test/",)) -> RdapClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return RdapClient(http_client=http, bootstrap=StaticBootstrap(urls), max_retries=retries)


def test_200_domain_object_is_registered() -> None:
    client = make_client(
        lambda req: httpx.Response(
            200, json={"objectClassName": "domain", "ldhName": "example.com"}
        )
    )
    result = client.check_domain("example.com")
    assert result.status is DomainCheckStatus.REGISTERED
    assert result.available is False


def test_json_404_from_authoritative_registry_is_unregistered() -> None:
    client = make_client(
        lambda req: httpx.Response(404, json={"errorCode": 404, "title": "Not Found"})
    )
    result = client.check_domain("unlikely-example.com")
    assert result.status is DomainCheckStatus.UNREGISTERED
    assert result.available is None


def test_ambiguous_html_404_is_not_treated_as_available() -> None:
    client = make_client(lambda req: httpx.Response(404, text="No RDAP service registered"))
    result = client.check_domain("example.com")
    assert result.status is DomainCheckStatus.UNKNOWN
    assert result.available is None


def test_reserved_404_is_reserved_not_available() -> None:
    client = make_client(
        lambda req: httpx.Response(
            404,
            json={
                "errorCode": 404,
                "title": "Reserved",
                "description": ["not available for registration"],
            },
        )
    )
    result = client.check_domain("reserved.example")
    assert result.status is DomainCheckStatus.RESERVED
    assert result.available is False


def test_wrong_domain_object_is_inconclusive() -> None:
    client = make_client(
        lambda req: httpx.Response(200, json={"objectClassName": "domain", "ldhName": "other.com"})
    )
    result = client.check_domain("example.com")
    assert result.status is DomainCheckStatus.UNKNOWN


def test_malformed_200_is_inconclusive() -> None:
    client = make_client(
        lambda req: httpx.Response(200, text="not-json", headers={"content-type": "text/plain"})
    )
    result = client.check_domain("example.com")
    assert result.status is DomainCheckStatus.UNKNOWN


def test_429_is_returned_immediately_without_internal_retry() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    result = make_client(handler, retries=2).check_domain("example.com")
    assert calls == 1
    assert result.status is DomainCheckStatus.RATE_LIMITED
    assert result.retries == 0


def test_timeout_is_network_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow registry", request=req)

    result = make_client(handler).check_domain("example.com")
    assert result.status is DomainCheckStatus.NETWORK_ERROR
    assert result.available is None


def test_missing_bootstrap_service_is_unsupported() -> None:
    result = make_client(
        lambda req: pytest.fail("HTTP should not be called"), urls=None
    ).check_domain("name.unknown")
    assert result.status is DomainCheckStatus.UNSUPPORTED


def test_transient_503_recovers_on_retry() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(404, json={"errorCode": 404, "title": "Not Found"})

    result = make_client(handler, retries=2).check_domain("freshname.com")
    assert result.status is DomainCheckStatus.UNREGISTERED
    assert result.retries == 1


def test_redirect_is_followed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "registry.test":
            return httpx.Response(
                302, headers={"Location": "https://final.test/domain/example.com"}
            )
        return httpx.Response(200, json={"objectClassName": "domain", "ldhName": "example.com"})

    result = make_client(handler).check_domain("example.com")
    assert result.status is DomainCheckStatus.REGISTERED


def test_authoritative_plain_404_is_unregistered() -> None:
    client = make_client(lambda req: httpx.Response(404, text="Not Found"))
    result = client.check_domain("unlikely-example.com")
    assert result.status is DomainCheckStatus.UNREGISTERED
    assert result.available is None


def test_429_reports_rate_limit_before_returning() -> None:
    calls = 0
    events: list[tuple[str, float | None]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0.5"})

    client = make_client(handler, retries=2)
    client.on_rate_limit = lambda host, retry_after: events.append((host, retry_after))
    result = client.check_domain("newname.com")

    assert calls == 1
    assert result.status is DomainCheckStatus.RATE_LIMITED
    assert events == [("registry.test", 0.5)]


def test_403_query_quota_is_rate_limited() -> None:
    client = make_client(
        lambda req: httpx.Response(
            403,
            text="<html><title>number of allowed queries exceeded.</title></html>",
        )
    )
    result = client.check_domain("candidate.wiki")
    assert result.status is DomainCheckStatus.RATE_LIMITED
    assert result.available is None


def test_dns_preflight_failure_skips_http_request() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"errorCode": 404})

    from domain_finder.infrastructure.whois.registry_dns import RegistryHostResolution

    client = make_client(handler)
    client.host_resolver = lambda host: RegistryHostResolution(
        backend_key=host, resolved=False, detail="registry DNS NXDOMAIN"
    )
    result = client.check_domain("candidate.com")
    assert calls == 0
    assert result.status is DomainCheckStatus.NETWORK_ERROR
    assert "dns" in (result.detail or "").lower()
