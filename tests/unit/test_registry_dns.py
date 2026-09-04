from __future__ import annotations

import dns.exception
import dns.resolver

from domain_finder.infrastructure.whois.registry_dns import RegistryDnsResolver


class CnameTarget:
    def __init__(self, target: str) -> None:
        self.target = target


class FakeResolver:
    def __init__(self, answers: dict[tuple[str, str], object]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def resolve(self, host: str, qtype: str, *, lifetime: float):
        self.calls.append((host, qtype))
        value = self.answers.get((host, qtype), dns.resolver.NoAnswer())
        if isinstance(value, Exception):
            raise value
        return value


def test_cname_aliases_collapse_to_shared_backend() -> None:
    fake = FakeResolver(
        {
            ("a.example", "CNAME"): [CnameTarget("shared.example.")],
            ("shared.example", "A"): [object()],
        }
    )
    result = RegistryDnsResolver(resolver=fake, timeout=0.2).resolve("a.example")
    assert result.backend_key == "shared.example"
    assert result.resolved is True


def test_nxdomain_is_bounded_transport_failure() -> None:
    fake = FakeResolver({("missing.example", "CNAME"): dns.resolver.NXDOMAIN()})
    result = RegistryDnsResolver(resolver=fake, timeout=0.2).resolve("missing.example")
    assert result.resolved is False
    assert "nxdomain" in (result.detail or "").lower()


def test_dns_timeout_is_transport_failure_not_availability() -> None:
    fake = FakeResolver({("slow.example", "CNAME"): dns.exception.Timeout()})
    result = RegistryDnsResolver(resolver=fake, timeout=0.2).resolve("slow.example")
    assert result.resolved is False
    assert "timeout" in (result.detail or "").lower()


def test_resolution_is_cached_per_host() -> None:
    fake = FakeResolver({("cached.example", "A"): [object()]})
    resolver = RegistryDnsResolver(resolver=fake, timeout=0.2)
    first = resolver.resolve("cached.example")
    second = resolver.resolve("cached.example")
    assert first == second
    assert fake.calls.count(("cached.example", "A")) == 1


def test_default_resolver_prefers_systemd_upstream_file(monkeypatch) -> None:
    import domain_finder.infrastructure.whois.registry_dns as registry_dns

    calls: list[str | None] = []

    class DummyResolver:
        pass

    def factory(filename=None):
        calls.append(filename)
        return DummyResolver()

    monkeypatch.setattr(registry_dns.Path, "exists", lambda self: True)
    monkeypatch.setattr(registry_dns.dns.resolver, "Resolver", factory)
    registry_dns.RegistryDnsResolver()
    assert calls == ["/run/systemd/resolve/resolv.conf"]


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now


def test_transient_dns_failure_expires_and_is_retried() -> None:
    clock = FakeClock()
    fake = FakeResolver({("registry.example", "CNAME"): dns.exception.Timeout()})
    resolver = RegistryDnsResolver(
        resolver=fake,
        timeout=0.2,
        failure_ttl=1.0,
        success_ttl=60.0,
        clock=clock.monotonic,
    )
    first = resolver.resolve("registry.example")
    assert first.resolved is False

    fake.answers[("registry.example", "CNAME")] = dns.resolver.NoAnswer()
    fake.answers[("registry.example", "A")] = [object()]
    assert resolver.resolve("registry.example").resolved is False

    clock.now += 1.1
    assert resolver.resolve("registry.example").resolved is True
