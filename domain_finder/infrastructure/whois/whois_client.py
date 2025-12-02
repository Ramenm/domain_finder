"""WHOIS client for domain availability checking."""

from __future__ import annotations

import time

import whois  # type: ignore

from domain_finder.domain.errors import DomainCheckError
from domain_finder.domain.models import DomainCheckResult


class WhoisClient:
    """Client for WHOIS domain checking."""

    def check_domain(self, domain: str) -> DomainCheckResult:
        """
        Check domain availability via WHOIS.

        Args:
            domain: Domain name to check (e.g., 'example.com')

        Returns:
            DomainCheckResult with availability status

        Raises:
            DomainCheckError: If check fails
        """
        try:
            data = whois.whois(domain)

            # In different implementations this can be dict or object
            def _get(attr: str):
                if isinstance(data, dict):
                    return data.get(attr)
                return getattr(data, attr, None)

            # If we see signs of registration, consider it taken
            dn = _get("domain_name")
            created = _get("creation_date")
            emails = _get("emails")

            available = not (dn or created or emails)

            return DomainCheckResult(
                domain=domain,
                available=available,
                source="whois",
                checked_at=time.time(),
            )
        except Exception as e:  # noqa: BLE001
            # WHOIS errors are treated as "could not confirm" => consider as TAKEN
            # to avoid false positives
            return DomainCheckResult(
                domain=domain,
                available=False,
                source="whois",
                checked_at=time.time(),
            )

