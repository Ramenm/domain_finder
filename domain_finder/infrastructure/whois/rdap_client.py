"""RDAP client for domain availability checking."""

from __future__ import annotations

import time
from typing import Optional

import httpx

from domain_finder.domain.errors import DomainCheckError
from domain_finder.domain.models import DomainCheckResult


class RdapClient:
    """Client for RDAP (Registration Data Access Protocol) domain checking."""

    def __init__(self, timeout: float = 10.0) -> None:
        """
        Initialize RDAP client.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.base_url = "https://rdap.org/domain"

    def check_domain(self, domain: str) -> DomainCheckResult:
        """
        Check domain availability via RDAP.

        RDAP: 404 -> available, 200 -> registered.

        Args:
            domain: Domain name to check (e.g., 'example.com')

        Returns:
            DomainCheckResult with availability status

        Raises:
            DomainCheckError: If check fails
        """
        url = f"{self.base_url}/{domain}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url)
                if response.status_code == 404:
                    available = True
                elif response.status_code == 200:
                    available = False
                else:
                    # In uncertain cases, consider as registered to avoid false positives
                    available = False

                return DomainCheckResult(
                    domain=domain,
                    available=available,
                    source="rdap",
                    checked_at=time.time(),
                )
        except httpx.TimeoutException:
            raise DomainCheckError(f"RDAP timeout for domain {domain}")
        except Exception as e:  # noqa: BLE001
            raise DomainCheckError(f"RDAP check failed for {domain}: {e}")

