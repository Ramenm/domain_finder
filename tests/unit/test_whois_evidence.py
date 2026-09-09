from __future__ import annotations

import pytest

from domain_finder.domain.models import DomainCheckStatus
from domain_finder.infrastructure.whois.whois_evidence import classify_whois_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Status: AVAILABLE", DomainCheckStatus.REGISTRABLE),
        ("Status: free", DomainCheckStatus.REGISTRABLE),
        ("Registration status: available", DomainCheckStatus.REGISTRABLE),
        ("Domain not found.", DomainCheckStatus.UNREGISTERED),
        ("No matching record.", DomainCheckStatus.UNREGISTERED),
        ("% No match", DomainCheckStatus.UNREGISTERED),
        ('No match for "candidate.test".', DomainCheckStatus.UNREGISTERED),
        ("%ERROR:101: no entries found", DomainCheckStatus.UNREGISTERED),
        ("Nothing found for this query.", DomainCheckStatus.UNREGISTERED),
        ("No such domain", DomainCheckStatus.UNREGISTERED),
        ("Domain is not registered", DomainCheckStatus.UNREGISTERED),
        ("The domain candidate.test was not found.", DomainCheckStatus.UNREGISTERED),
        ("The queried object does not exist: DOMAIN NOT FOUND", DomainCheckStatus.UNREGISTERED),
        ("Domain candidate.test is available for registration", DomainCheckStatus.REGISTRABLE),
        ("Domain Status: No Object Found", DomainCheckStatus.UNREGISTERED),
        ("No_Se_Encontro_El_Objeto/Object_Not_Found", DomainCheckStatus.UNREGISTERED),
    ],
)
def test_authoritative_absence_and_registrability_are_distinct(
    raw: str, expected: DomainCheckStatus
) -> None:
    evidence = classify_whois_text("candidate.test", raw)
    assert evidence is not None
    assert evidence.status is expected


@pytest.mark.parametrize(
    "raw",
    [
        "No Data Found\nFAILURE TO LOCATE A RECORD IS NOT INDICATIVE OF AVAILABILITY.",
        "This service may be unavailable at any time.",
        "For information about available domains, visit the registry website.",
        "",
    ],
)
def test_ambiguous_or_policy_text_is_not_availability(raw: str) -> None:
    assert classify_whois_text("candidate.us", raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "Domain Name: google.test\nRegistrar: Example Registrar\nName Server: ns1.example.test",
        "Domain: google.test\nStatus: registered",
        "Domain Name: google.test\nCreation Date: 2020-01-01",
    ],
)
def test_strong_registration_evidence_is_registered(raw: str) -> None:
    evidence = classify_whois_text("google.test", raw)
    assert evidence is not None
    assert evidence.status is DomainCheckStatus.REGISTERED


def test_has_not_been_registered_is_explicit_absence() -> None:
    evidence = classify_whois_text(
        "candidate.hk",
        "The domain has not been registered.",
    )
    assert evidence is not None
    assert evidence.status is DomainCheckStatus.UNREGISTERED
