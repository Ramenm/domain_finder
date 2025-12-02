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
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(url)
                
                # RDAP logic: 404 means domain is available (not registered)
                # 200 means domain is registered (not available)
                # Other status codes need careful handling
                if response.status_code == 404:
                    available = True
                elif response.status_code == 200:
                    # 200 means domain is registered - check response to be sure
                    try:
                        data = response.json()
                        # If we get valid JSON with domain info, it's registered
                        if isinstance(data, dict) and (data.get("handle") or data.get("ldhName")):
                            available = False
                        else:
                            # Empty or invalid response - treat as available (might be false positive)
                            available = True
                    except Exception:  # noqa: BLE001
                        # Can't parse JSON - if 200 with content, likely registered
                        # But if response is empty, might be available
                        if response.text and len(response.text.strip()) > 0:
                            available = False
                        else:
                            # Empty response on 200 - unusual, treat as available
                            available = True
                elif response.status_code in (429, 503, 502, 504):
                    # Rate limit or service unavailable - raise error to retry
                    raise DomainCheckError(
                        f"RDAP service unavailable (status {response.status_code}) for domain {domain}"
                    )
                else:
                    # Unknown status - be conservative and mark as unavailable
                    # to avoid false positives
                    available = False

                return DomainCheckResult(
                    domain=domain,
                    available=available,
                    source="rdap",
                    checked_at=time.time(),
                )
        except httpx.TimeoutException:
            raise DomainCheckError(f"Превышено время ожидания ответа от RDAP для домена {domain}")
        except DomainCheckError:
            # Re-raise domain check errors
            raise
        except Exception as e:  # noqa: BLE001
            raise DomainCheckError(f"Ошибка при проверке домена {domain} через RDAP: {e}")

