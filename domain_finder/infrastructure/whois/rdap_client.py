"""RDAP client for domain availability checking."""

from __future__ import annotations

import time
from typing import Optional

import httpx

from domain_finder.domain.errors import DomainCheckError
from domain_finder.domain.models import DomainCheckResult

# Status codes that can be retried
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class RdapClient:
    """Client for RDAP (Registration Data Access Protocol) domain checking."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        """
        Initialize RDAP client.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts for retryable errors
            http_client: Optional shared HTTP client (for connection pooling)
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://rdap.org/domain"
        self._http_client = http_client  # Shared client for connection pooling

    def _parse_json_safe(self, response: httpx.Response) -> Optional[dict]:
        """
        Safely parse JSON from response.
        
        Args:
            response: HTTP response
            
        Returns:
            Parsed JSON dict or None if not JSON
        """
        content_type = (response.headers.get("content-type") or "").lower()
        if "json" not in content_type:
            return None
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            return None
        return None

    def _is_not_found_error(self, data: dict) -> bool:
        """
        Check if RDAP response indicates domain not found.
        
        Args:
            data: Parsed JSON response
            
        Returns:
            True if response indicates domain not found
        """
        # Check errorCode field
        error_code = data.get("errorCode")
        if isinstance(error_code, int) and error_code == 404:
            return True

        # Check title and detail fields
        title = (data.get("title") or "").lower()
        detail = (data.get("detail") or "").lower()
        combined = f"{title} {detail}"
        
        not_found_indicators = [
            "not found",
            "object does not exist",
            "domain not found",
            "does not exist",
        ]
        return any(indicator in combined for indicator in not_found_indicators)

    def _is_domain_object(self, data: dict, domain: str) -> bool:
        """
        Check if RDAP response contains a valid domain object.
        
        Args:
            data: Parsed JSON response
            domain: Domain name being checked
            
        Returns:
            True if response contains valid domain object
        """
        if data.get("objectClassName") != "domain":
            return False

        # Check domain name matches
        ldh_name = (data.get("ldhName") or data.get("unicodeName") or "").lower()
        if ldh_name and ldh_name != domain.lower():
            # Response for different domain - don't trust it
            return False
        
        # Check for domain identifiers
        return bool(data.get("handle") or data.get("ldhName") or data.get("unicodeName"))

    def check_domain(self, domain: str) -> DomainCheckResult:
        """
        Check domain availability via RDAP with retry logic.

        RDAP spec: 200 with domain object = registered, 404 with not found = available.

        Args:
            domain: Domain name to check (e.g., 'example.com')

        Returns:
            DomainCheckResult with availability status

        Raises:
            DomainCheckError: If check fails after retries
        """
        url = f"{self.base_url}/{domain}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # Use shared client if available, otherwise create temporary one
                if self._http_client:
                    response = self._http_client.get(url, follow_redirects=True)
                else:
                    with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                        response = client.get(url)
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt == self.max_retries:
                    raise DomainCheckError(
                        f"Превышено время ожидания ответа от RDAP для домена {domain}"
                    ) from e
                # Exponential backoff
                time.sleep(0.2 * (2 ** (attempt - 1)))
                continue
            except httpx.HTTPError as e:
                last_exc = e
                if attempt == self.max_retries:
                    raise DomainCheckError(
                        f"HTTP ошибка при запросе RDAP для домена {domain}: {e}"
                    ) from e
                time.sleep(0.2 * (2 ** (attempt - 1)))
                continue

            data = self._parse_json_safe(response)
            status = response.status_code

            try:
                # 2xx: Domain object found (registered)
                if 200 <= status < 300:
                    if data is None:
                        # 200 without JSON - very unusual, can't determine
                        raise DomainCheckError(
                            f"RDAP вернул {status} без JSON для домена {domain}"
                        )

                    if self._is_domain_object(data, domain):
                        # Valid domain object found - domain is registered
                        available = False
                    elif self._is_not_found_error(data):
                        # Error response in 2xx (unusual but possible)
                        available = True
                    else:
                        # Can't interpret response
                        raise DomainCheckError(
                            f"Неожиданный формат RDAP ответа для домена {domain}"
                        )

                # 404: Either "not found" or rdap.org has no service for this TLD
                elif status == 404:
                    if data is not None and self._is_not_found_error(data):
                        # RDAP "not found" error - domain is available
                        available = True
                    else:
                        # 404 without JSON - most likely means "not found" = domain available
                        # Even if TLD doesn't have RDAP support, 404 typically means domain not found
                        # This is safer than throwing error - we assume domain is available
                        available = True

                # Retryable errors
                elif status in RETRYABLE_STATUSES:
                    if attempt == self.max_retries:
                        raise DomainCheckError(
                            f"RDAP временно недоступен (status {status}) для домена {domain}"
                        )
                    # Respect Retry-After header if present
                    retry_after = response.headers.get("Retry-After")
                    delay = 0.2 * (2 ** (attempt - 1))
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, float(retry_after))
                    time.sleep(delay)
                    continue

                # Other 4xx/5xx: Error, can't determine availability
                else:
                    raise DomainCheckError(
                        f"Неожиданный HTTP статус от RDAP ({status}) для домена {domain}"
                    )

                # Successfully determined availability
                return DomainCheckResult(
                    domain=domain,
                    available=available,
                    source="rdap",
                    checked_at=time.time(),
                )

            except DomainCheckError as e:
                last_exc = e
                # For logical errors, retry usually won't help, but try anyway
                if attempt == self.max_retries:
                    raise
                time.sleep(0.2 * (2 ** (attempt - 1)))
                continue

        # Should not reach here
        raise DomainCheckError(
            f"Ошибка при проверке домена {domain} через RDAP: {last_exc}"
        ) from last_exc

