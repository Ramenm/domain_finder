from __future__ import annotations

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.infrastructure.whois.checker import DomainChecker


class FakeRdap:
    def __init__(self, status: DomainCheckStatus) -> None:
        self.status = status
        self.calls = 0

    def check_domain(self, domain: str) -> DomainCheckResult:
        self.calls += 1
        return DomainCheckResult(domain=domain, status=self.status, source="rdap", checked_at=1.0)


class FakeWhois:
    def __init__(
        self, status: DomainCheckStatus = DomainCheckStatus.REGISTERED, fail: bool = False
    ) -> None:
        self.status = status
        self.fail = fail
        self.calls = 0

    def check_domain(self, domain: str) -> DomainCheckResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("whois transport failed")
        return DomainCheckResult(domain=domain, status=self.status, source="whois", checked_at=1.0)


def make_checker(rdap: FakeRdap, whois: FakeWhois, fallback: bool = True) -> DomainChecker:
    checker = DomainChecker(whois_fallback=fallback, dns_prefilter=False, dns_fallback=False)
    checker.rdap_client = rdap
    checker.whois_client = whois
    return checker


def test_definitive_rdap_does_not_call_whois() -> None:
    rdap = FakeRdap(DomainCheckStatus.AVAILABLE)
    whois = FakeWhois(DomainCheckStatus.REGISTERED)
    result = make_checker(rdap, whois).check_domain("newname.com")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert whois.calls == 0


def test_inconclusive_rdap_uses_whois_fallback() -> None:
    rdap = FakeRdap(DomainCheckStatus.NETWORK_ERROR)
    whois = FakeWhois(DomainCheckStatus.REGISTERED)
    result = make_checker(rdap, whois).check_domain("example.com")
    assert result.status is DomainCheckStatus.REGISTERED
    assert whois.calls == 1


def test_whois_failure_stays_inconclusive() -> None:
    rdap = FakeRdap(DomainCheckStatus.NETWORK_ERROR)
    whois = FakeWhois(fail=True)
    result = make_checker(rdap, whois).check_domain("example.com")
    assert result.status is DomainCheckStatus.NETWORK_ERROR
    assert result.available is None


class HostedRdap(FakeRdap):
    def get_rdap_host(self, domain: str) -> str:
        return "registry.example"


class RecordingLimiter:
    def __init__(self) -> None:
        self.penalties: list[str] = []
        self.rewards: list[str] = []

    def acquire(self, host: str):
        from contextlib import nullcontext

        return nullcontext()

    def penalize(self, host: str, retry_after: float | None = None) -> None:
        self.penalties.append(host)

    def reward(self, host: str) -> None:
        self.rewards.append(host)


def test_rdap_rate_limit_penalizes_only_that_registry() -> None:
    checker = make_checker(HostedRdap(DomainCheckStatus.RATE_LIMITED), FakeWhois(), fallback=False)
    limiter = RecordingLimiter()
    checker._rdap_limiter = limiter
    checker._rdap_checked("candidate.ai")
    assert limiter.penalties == ["registry.example"]
    assert limiter.rewards == []


def test_definitive_rdap_result_recovers_registry_rate() -> None:
    checker = make_checker(HostedRdap(DomainCheckStatus.AVAILABLE), FakeWhois(), fallback=False)
    limiter = RecordingLimiter()
    checker._rdap_limiter = limiter
    checker._rdap_checked("candidate.com")
    assert limiter.rewards == ["registry.example"]
    assert limiter.penalties == []


def test_checker_wires_transient_rate_limit_callback() -> None:
    checker = DomainChecker(whois_fallback=False, dns_prefilter=False)
    try:
        callback = checker.rdap_client.on_rate_limit
        assert callback is not None
        callback("registry.example", 1.5)
        assert checker._rdap_limiter.rate_interval("registry.example") == 1.5
    finally:
        checker.close()


class PenalizedLimiter(RecordingLimiter):
    def rate_interval(self, host: str) -> float:
        return 1.0

    def is_throttled(self, host: str) -> bool:
        return True


def test_penalized_registry_uses_definitive_whois_before_waiting_for_rdap() -> None:
    rdap = HostedRdap(DomainCheckStatus.AVAILABLE)
    whois = FakeWhois(DomainCheckStatus.AVAILABLE)
    checker = make_checker(rdap, whois, fallback=True)
    checker._rdap_limiter = PenalizedLimiter()

    result = checker.check_domain("candidate.ai")

    assert result.status is DomainCheckStatus.AVAILABLE
    assert result.source == "whois"
    assert whois.calls == 1
    assert rdap.calls == 0


def test_registry_backend_key_collapses_cname_aliases(monkeypatch) -> None:
    import domain_finder.infrastructure.whois.checker as checker_module
    from domain_finder.infrastructure.whois.registry_dns import RegistryHostResolution

    monkeypatch.setattr(
        checker_module._registry_dns,
        "resolve",
        lambda _host: RegistryHostResolution("shared.registry.example", True),
    )
    assert checker_module._registry_backend_key("rdap.nic.one") == "shared.registry.example"
    assert checker_module._registry_backend_key("rdap.nic.two") == "shared.registry.example"


class FakeDns:
    def __init__(self, value: bool | None) -> None:
        self.value = value
        self.calls = 0

    def has_nameservers(self, domain: str) -> bool | None:
        self.calls += 1
        return self.value


def test_late_dns_fallback_proves_registered_after_inconclusive_sources() -> None:
    rdap = FakeRdap(DomainCheckStatus.UNSUPPORTED)
    whois = FakeWhois(DomainCheckStatus.UNKNOWN)
    checker = DomainChecker(whois_fallback=True, dns_prefilter=False, dns_fallback=True)
    checker.rdap_client = rdap
    checker.whois_client = whois
    checker.dns_prefilter = FakeDns(True)
    result = checker.check_domain("miit.gov.cn")
    assert result.status is DomainCheckStatus.REGISTERED
    assert result.source == "dns"
    assert whois.calls == 0


def test_late_dns_fallback_never_turns_missing_dns_into_available() -> None:
    rdap = FakeRdap(DomainCheckStatus.UNSUPPORTED)
    whois = FakeWhois(DomainCheckStatus.UNKNOWN)
    checker = DomainChecker(whois_fallback=True, dns_prefilter=False, dns_fallback=True)
    checker.rdap_client = rdap
    checker.whois_client = whois
    checker.dns_prefilter = FakeDns(False)
    result = checker.check_domain("random.us")
    assert result.status is DomainCheckStatus.UNSUPPORTED
    assert result.available is None


class CapabilityWhois(FakeWhois):
    def __init__(self, status: DomainCheckStatus, can_confirm_available: bool) -> None:
        super().__init__(status=status)
        self.can_confirm_available = can_confirm_available

    def supports_availability(self, domain: str) -> bool:
        return self.can_confirm_available


def test_rate_limited_unknown_zone_skips_useless_whois() -> None:
    rdap = FakeRdap(DomainCheckStatus.RATE_LIMITED)
    whois = CapabilityWhois(DomainCheckStatus.UNKNOWN, can_confirm_available=False)
    checker = DomainChecker(whois_fallback=True, dns_prefilter=False, dns_fallback=True)
    checker.rdap_client = rdap
    checker.whois_client = whois
    checker.dns_prefilter = FakeDns(False)
    result = checker.check_domain("candidate.aaa")
    assert result.status is DomainCheckStatus.RATE_LIMITED
    assert whois.calls == 0


def test_known_whois_zone_still_falls_back_for_availability() -> None:
    rdap = FakeRdap(DomainCheckStatus.UNSUPPORTED)
    whois = CapabilityWhois(DomainCheckStatus.AVAILABLE, can_confirm_available=True)
    checker = DomainChecker(whois_fallback=True, dns_prefilter=False, dns_fallback=True)
    checker.rdap_client = rdap
    checker.whois_client = whois
    checker.dns_prefilter = FakeDns(False)
    result = checker.check_domain("candidate.ru")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert whois.calls == 1


class RecordingProfiles:
    def __init__(self) -> None:
        self.routing = []
        self.observations = []

    def record_routing(self, tld: str, **kwargs) -> None:
        self.routing.append((tld, kwargs))

    def record_observation(self, tld: str, protocol: str, status, latency_ms) -> None:
        self.observations.append((tld, protocol, status, latency_ms))


def test_rdap_result_records_dynamic_registry_profile(monkeypatch) -> None:
    profiles = RecordingProfiles()
    rdap = HostedRdap(DomainCheckStatus.AVAILABLE)
    checker = DomainChecker(
        whois_fallback=False,
        dns_prefilter=False,
        profile_store=profiles,
    )
    checker.rdap_client = rdap
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.checker._registry_backend_key",
        lambda _host: "shared.registry.backend",
    )
    result = checker._rdap_checked("candidate.com")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert profiles.routing == [
        (
            "com",
            {"rdap_host": "registry.example", "backend_key": "shared.registry.backend"},
        )
    ]
    assert profiles.observations[0][0:3] == ("com", "rdap", DomainCheckStatus.AVAILABLE)


class RoutingRdap(FakeRdap):
    def get_rdap_host(self, domain: str) -> str | None:
        if domain.endswith((".ai", ".info")):
            return "identity.example"
        if domain.endswith(".com"):
            return "verisign.example"
        return None


def test_batch_order_is_interleaved_across_registry_backends(monkeypatch) -> None:
    checker = make_checker(RoutingRdap(DomainCheckStatus.AVAILABLE), FakeWhois(), fallback=False)
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.checker._registry_backend_key",
        lambda host: host,
    )
    domains = [
        "a.ai",
        "b.info",
        "c.ai",
        "one.com",
        "alpha.de",
        "two.com",
        "beta.de",
    ]
    ordered = checker._interleave_by_registry(domains)
    assert ordered[:3] == ["a.ai", "one.com", "alpha.de"]
    assert set(ordered) == set(domains)
    assert ordered.index("b.info") > ordered.index("one.com")
    assert ordered.index("c.ai") > ordered.index("two.com")
