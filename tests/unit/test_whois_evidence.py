from __future__ import annotations

import pytest

from domain_finder.domain.models import DomainCheckStatus
from domain_finder.infrastructure.whois.whois_evidence import classify_whois_text


@pytest.mark.parametrize(
    "raw",
    [
        "Status: AVAILABLE",
        "Status: free",
        "Registration status: available",
        "Domain not found.",
        "No matching record.",
        "% No match",
        'No match for "candidate.test".',
        "%ERROR:101: no entries found",
        "Nothing found for this query.",
        "No such domain",
        "Domain is not registered",
        "The domain candidate.test was not found.",
        "The queried object does not exist: DOMAIN NOT FOUND",
        "Domain candidate.test is available for registration",
        "Domain Status: No Object Found",
        "No_Se_Encontro_El_Objeto/Object_Not_Found",
    ],
)
def test_explicit_authoritative_free_evidence_is_available(raw: str) -> None:
    evidence = classify_whois_text("candidate.test", raw)
    assert evidence is not None
    assert evidence.status is DomainCheckStatus.AVAILABLE


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


def test_has_not_been_registered_is_explicit_availability() -> None:
    evidence = classify_whois_text(
        "candidate.hk",
        "The domain has not been registered.",
    )
    assert evidence is not None
    assert evidence.status is DomainCheckStatus.AVAILABLE
