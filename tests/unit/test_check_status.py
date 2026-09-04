from __future__ import annotations

import time

import pytest

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus


@pytest.mark.parametrize(
    ("status", "available"),
    [
        (DomainCheckStatus.AVAILABLE, True),
        (DomainCheckStatus.REGISTERED, False),
        (DomainCheckStatus.UNKNOWN, None),
        (DomainCheckStatus.RATE_LIMITED, None),
        (DomainCheckStatus.NETWORK_ERROR, None),
        (DomainCheckStatus.UNSUPPORTED, None),
        (DomainCheckStatus.INVALID, None),
    ],
)
def test_status_controls_availability(status: DomainCheckStatus, available: bool | None) -> None:
    result = DomainCheckResult(
        domain="example.com", status=status, source="rdap", checked_at=time.time()
    )
    assert result.available is available
    assert result.is_definitive is (available is not None)


def test_legacy_boolean_result_is_inferred_for_compatibility() -> None:
    available = DomainCheckResult(domain="free.test", available=True, source="rdap", checked_at=1.0)
    registered = DomainCheckResult(
        domain="taken.test", available=False, source="whois", checked_at=1.0
    )
    unknown = DomainCheckResult(
        domain="unknown.test", available=False, source="unknown", checked_at=1.0
    )

    assert available.status is DomainCheckStatus.AVAILABLE
    assert registered.status is DomainCheckStatus.REGISTERED
    assert unknown.status is DomainCheckStatus.UNKNOWN
    assert unknown.available is None


def test_error_status_keeps_detail_without_becoming_registered() -> None:
    result = DomainCheckResult(
        domain="example.com",
        status=DomainCheckStatus.NETWORK_ERROR,
        source="rdap",
        checked_at=1.0,
        detail="connect timeout",
    )
    assert result.available is None
    assert result.detail == "connect timeout"
