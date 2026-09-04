from __future__ import annotations

import pytest

from domain_finder.domain.models import DomainCheckStatus
from domain_finder.infrastructure.whois.whois_client import WhoisClient


def test_whois_exception_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(domain: str):
        raise TimeoutError("port 43 timeout")

    monkeypatch.setattr("domain_finder.infrastructure.whois.whois_client.whois.whois", fail)
    result = WhoisClient().check_domain("example.com")
    assert result.status is DomainCheckStatus.NETWORK_ERROR
    assert result.available is None
    assert "timeout" in (result.detail or "")


@pytest.mark.parametrize(
    ("domain", "message"),
    [
        ("free-example.io", "Domain not found."),
        ("free-example.de", "Domain: free-example.de\nStatus: free"),
        ("free-example.be", "Domain:\tfree-example.be\r\nStatus:\tAVAILABLE"),
        ("free-example.ru", "No entries found for the selected source(s)."),
    ],
)
def test_verified_registry_free_markers_are_available(
    monkeypatch: pytest.MonkeyPatch, domain: str, message: str
) -> None:
    def fail(_domain: str):
        raise RuntimeError(message)

    monkeypatch.setattr("domain_finder.infrastructure.whois.whois_client.whois.whois", fail)
    result = WhoisClient().check_domain(domain)
    assert result.status is DomainCheckStatus.AVAILABLE
    assert result.available is True


def test_ambiguous_us_no_data_marker_is_not_treated_as_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_domain: str):
        raise RuntimeError("No Data Found\nNOTE: FAILURE TO LOCATE A RECORD IS NOT INDICATIVE")

    monkeypatch.setattr("domain_finder.infrastructure.whois.whois_client.whois.whois", fail)
    result = WhoisClient().check_domain("maybe-free.us")
    assert result.status is DomainCheckStatus.NETWORK_ERROR
    assert result.available is None


class EmptyWhois:
    domain_name = None
    creation_date = None
    emails = None


def test_generic_empty_whois_response_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda domain: EmptyWhois(),
    )
    result = WhoisClient().check_domain("unknown-zone.example")
    assert result.status is DomainCheckStatus.UNKNOWN
    assert result.available is None


@pytest.mark.parametrize("domain", ["candidate.me", "candidate.co", "candidate.live"])
def test_empty_parser_response_never_proves_availability(
    monkeypatch: pytest.MonkeyPatch, domain: str
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: EmptyWhois(),
    )
    result = WhoisClient(raw_fallback=False).check_domain(domain)
    assert result.status is DomainCheckStatus.UNKNOWN
    assert result.available is None


def test_ai_domain_not_found_marker_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_domain: str):
        raise RuntimeError("Domain not found.")

    monkeypatch.setattr("domain_finder.infrastructure.whois.whois_client.whois.whois", fail)
    result = WhoisClient().check_domain("candidate.ai")
    assert result.status is DomainCheckStatus.AVAILABLE


def test_raw_whois_recovers_free_eu_from_empty_library_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: EmptyWhois(),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: "Domain: candidate.eu\nStatus: AVAILABLE",
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.eu")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert result.available is True


def test_raw_whois_recovers_free_se_after_library_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: (_ for _ in ()).throw(TimeoutError("parser timeout")),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: '# domain "candidate.se" not found.',
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.se")
    assert result.status is DomainCheckStatus.AVAILABLE


def test_raw_whois_does_not_guess_us_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: EmptyWhois(),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: (
            "No Data Found. FAILURE TO LOCATE A RECORD IS NOT INDICATIVE OF AVAILABILITY."
        ),
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.us")
    assert result.status is DomainCheckStatus.UNKNOWN
    assert result.available is None


def test_unicode_domain_is_converted_to_ascii_wire_form() -> None:
    from domain_finder.infrastructure.whois.whois_client import _to_ascii_domain

    assert _to_ascii_domain("пример.рф") == "xn--e1afmkfd.xn--p1ai"


@pytest.mark.parametrize(
    ("domain", "raw"),
    [
        ("candidate.am", "% No match"),
        ("candidate.bg", "registration status: available"),
        ("candidate.by", "object does not exist"),
        ("candidate.ee", "Domain not found"),
        ("candidate.hu", "Nincs talalat / No match"),
        ("candidate.hr", "%ERROR: No entries found"),
        ("candidate.cl", "candidate.cl: no entries found."),
        ("candidate.kz", "*** Nothing found for this query."),
        ("candidate.im", "The domain candidate.im was not found."),
        ("candidate.lt", "Domain: candidate.lt Status: available"),
    ],
)
def test_more_authoritative_cc_tld_free_markers(
    monkeypatch: pytest.MonkeyPatch, domain: str, raw: str
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: EmptyWhois(),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: raw,
    )
    result = WhoisClient(raw_fallback=True).check_domain(domain)
    assert result.status is DomainCheckStatus.AVAILABLE


@pytest.mark.parametrize(
    ("domain", "raw"),
    [
        ("candidate.lu", "% No such domain"),
        ("candidate.lv", "Domain: candidate.lv Status: free"),
        ("candidate.mk", "%ERROR:101: no entries found"),
        ("candidate.pk", "Status: Not Registered, and may be available if valid Available: Yes."),
        ("candidate.md", "No entries found [ No match for ]"),
        ("candidate.rs", "%ERROR:103: Domain is not registered"),
        ("candidate.si", "% No entries found for the selected source(s)."),
        ("candidate.sk", "Domain not found."),
        ("candidate.ve", "%ERROR:101: no entries found"),
        ("candidate.cn", "No matching record."),
    ],
)
def test_additional_authoritative_cc_tld_free_markers(
    monkeypatch: pytest.MonkeyPatch, domain: str, raw: str
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: EmptyWhois(),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: raw,
    )
    result = WhoisClient(raw_fallback=True).check_domain(domain)
    assert result.status is DomainCheckStatus.AVAILABLE


class WeakDomainOnlyWhois:
    def __init__(self, domain: str, status=None) -> None:
        self.domain_name = domain
        self.creation_date = None
        self.emails = None
        self.registrar = None
        self.status = status
        self.name_servers = None


def test_parsed_available_status_wins_over_domain_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda domain: WeakDomainOnlyWhois(domain, status="available"),
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.lt")
    assert result.status is DomainCheckStatus.AVAILABLE


def test_weak_domain_name_is_disambiguated_by_raw_free_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda domain: WeakDomainOnlyWhois(domain),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda domain: f"Domain Name: {domain}\nThe domain {domain} was not found.",
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.im")
    assert result.status is DomainCheckStatus.AVAILABLE


def test_weak_domain_name_can_be_confirmed_registered_by_raw_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda domain: WeakDomainOnlyWhois(domain),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda domain: f"Domain Name: {domain}\nDomain Managers\nName\nThe IM Registry",
    )
    result = WhoisClient(raw_fallback=True).check_domain("gov.im")
    assert result.status is DomainCheckStatus.REGISTERED


def test_weak_domain_name_without_raw_proof_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda domain: WeakDomainOnlyWhois(domain),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: None,
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.im")
    assert result.status is DomainCheckStatus.UNKNOWN


@pytest.mark.parametrize(
    ("domain", "raw"),
    [
        ("candidate.ir", "%ERROR:101: no entries found"),
        ("candidate.su", "No entries found for the selected source(s)."),
        ("candidate.gg", "NOT FOUND"),
        ("candidate.st", "No entries found for domain candidate.st"),
        ("candidate.sa", "No Match for domain: candidate.sa"),
        ("candidate.ma", "No Object Found"),
        ("candidate.ws", "The queried object does not exist: candidate.ws"),
        ("candidate.my", "Domain candidate.my is available for registration"),
        ("candidate.ie", "Not found: candidate.ie"),
        ("candidate.sh", "Domain not found."),
        ("candidate.ge", 'No match for "CANDIDATE.GE".'),
        ("candidate.la", "The queried object does not exist: DOMAIN NOT FOUND"),
    ],
)
def test_high_impact_tranco_cc_tld_free_markers(
    monkeypatch: pytest.MonkeyPatch, domain: str, raw: str
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: EmptyWhois(),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: raw,
    )
    result = WhoisClient(raw_fallback=True).check_domain(domain)
    assert result.status is DomainCheckStatus.AVAILABLE


@pytest.mark.parametrize(
    ("domain", "raw"),
    [
        (
            "candidate.kr",
            "The requested domain was not found in the Registry or Registrar's WHOIS Server.",
        ),
        ("candidate.pe", "Domain Name: candidate.pe Domain Status: No Object Found"),
    ],
)
def test_kr_and_pe_authoritative_free_markers(
    monkeypatch: pytest.MonkeyPatch, domain: str, raw: str
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: EmptyWhois(),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: raw,
    )
    result = WhoisClient(raw_fallback=True).check_domain(domain)
    assert result.status is DomainCheckStatus.AVAILABLE


def test_pe_parsed_no_object_found_wins_over_domain_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda domain: WeakDomainOnlyWhois(domain, status="No Object Found"),
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.pe")
    assert result.status is DomainCheckStatus.AVAILABLE


def test_raw_first_skips_parser_for_definitive_free_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    parser_calls = 0

    def parser(_domain: str):
        nonlocal parser_calls
        parser_calls += 1
        return EmptyWhois()

    monkeypatch.setattr("domain_finder.infrastructure.whois.whois_client.whois.whois", parser)
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: "Domain: candidate.de Status: free",
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.de")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert parser_calls == 0


def test_raw_first_can_prove_registered_without_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: (_ for _ in ()).throw(AssertionError("parser should not run")),
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: "Domain: google.lt Status: registered Registrar: MarkMonitor",
    )
    result = WhoisClient(raw_fallback=True).check_domain("google.lt")
    assert result.status is DomainCheckStatus.REGISTERED


def test_unlisted_tld_uses_dynamic_iana_referral_for_explicit_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._iana_whois_server",
        lambda _tld: "whois.registry.test",
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._socket_query",
        lambda _server, _query: "Status: AVAILABLE",
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda _domain: (_ for _ in ()).throw(AssertionError("raw should be enough")),
    )
    result = WhoisClient(raw_fallback=True).check_domain("candidate.zztest")
    assert result.status is DomainCheckStatus.AVAILABLE


def test_supports_availability_is_discovered_from_iana_referral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._iana_whois_server",
        lambda _tld: "whois.registry.test",
    )
    assert WhoisClient(raw_fallback=True).supports_availability("candidate.zztest") is True


class RecordingRegistryProfiles:
    def __init__(self) -> None:
        self.routing = []
        self.observations = []
        self.probes = []

    def record_routing(self, tld: str, **kwargs) -> None:
        self.routing.append((tld, kwargs))

    def record_observation(self, tld: str, protocol: str, status, latency_ms) -> None:
        self.observations.append((tld, protocol, status, latency_ms))

    def record_whois_probe(self, tld: str, status, evidence_code) -> None:
        self.probes.append((tld, status, evidence_code))


def test_raw_whois_records_dynamic_registry_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    profiles = RecordingRegistryProfiles()
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._iana_whois_server",
        lambda _tld: "whois.registry.test",
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._socket_query",
        lambda _server, _query: "Domain not found.",
    )
    result = WhoisClient(raw_fallback=True, profile_store=profiles).check_domain("candidate.zztest")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert profiles.routing == [("zztest", {"whois_server": "whois.registry.test"})]
    assert profiles.probes == [("zztest", DomainCheckStatus.AVAILABLE, "domain_not_found")]
    assert profiles.observations[0][0:3] == ("zztest", "whois", DomainCheckStatus.AVAILABLE)


def test_parser_explicit_availability_records_registry_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles = RecordingRegistryProfiles()
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client._raw_whois",
        lambda _domain: None,
    )
    monkeypatch.setattr(
        "domain_finder.infrastructure.whois.whois_client.whois.whois",
        lambda domain: WeakDomainOnlyWhois(domain, status="available"),
    )
    result = WhoisClient(raw_fallback=True, profile_store=profiles).check_domain("candidate.zztest")
    assert result.status is DomainCheckStatus.AVAILABLE
    assert profiles.probes == [("zztest", DomainCheckStatus.AVAILABLE, "parser_status_available")]
