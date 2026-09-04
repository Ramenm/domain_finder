from __future__ import annotations

from domain_finder.domain.models import DomainCheckStatus
from domain_finder.infrastructure.whois.registry_profiles import RegistryProfileStore


def test_registry_profile_persists_dynamic_routing(tmp_path) -> None:
    path = tmp_path / "profiles.sqlite3"
    store = RegistryProfileStore(path)
    store.record_routing(
        "wiki",
        rdap_host="rdap.nic.wiki",
        backend_key="rdap.prod.aws.dnrs.godaddy",
        whois_server="whois.nic.wiki",
    )
    store.close()

    reopened = RegistryProfileStore(path)
    profile = reopened.get("wiki")
    assert profile is not None
    assert profile.rdap_host == "rdap.nic.wiki"
    assert profile.backend_key == "rdap.prod.aws.dnrs.godaddy"
    assert profile.whois_server == "whois.nic.wiki"
    reopened.close()


def test_registry_profile_accumulates_latency_and_outcomes(tmp_path) -> None:
    store = RegistryProfileStore(tmp_path / "profiles.sqlite3")
    store.record_observation("com", "rdap", DomainCheckStatus.AVAILABLE, 100.0)
    store.record_observation("com", "rdap", DomainCheckStatus.REGISTERED, 300.0)
    store.record_observation("com", "rdap", DomainCheckStatus.RATE_LIMITED, 50.0)

    profile = store.get("com")
    assert profile is not None
    assert profile.rdap_observations == 3
    assert profile.rate_limits == 1
    assert profile.rdap_ema_ms == 140.0
    store.close()


def test_whois_availability_capability_requires_repeated_explicit_evidence(tmp_path) -> None:
    store = RegistryProfileStore(tmp_path / "profiles.sqlite3")
    store.record_whois_probe("me", DomainCheckStatus.AVAILABLE, "domain_not_found")
    assert store.get("me").whois_can_confirm_available is False

    store.record_whois_probe("me", DomainCheckStatus.AVAILABLE, "domain_not_found")
    profile = store.get("me")
    assert profile.whois_can_confirm_available is True
    assert profile.whois_free_confirmations == 2
    assert profile.whois_evidence_code == "domain_not_found"
    store.close()
