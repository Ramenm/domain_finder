"""Authoritative RDAP client for domain availability checks."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.infrastructure.whois.rdap_bootstrap import RdapBootstrap
from domain_finder.infrastructure.whois.registry_dns import RegistryHostResolution

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class RdapClient:
    """Query the authoritative RDAP service selected by the IANA bootstrap."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        http_client: httpx.Client | None = None,
        bootstrap: RdapBootstrap | None = None,
        fallback_to_rdap_org: bool = False,
        host_resolver: Callable[[str], RegistryHostResolution] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._http_client = http_client
        self._bootstrap = bootstrap or RdapBootstrap(http_client=http_client, timeout=timeout)
        self._fallback_to_rdap_org = fallback_to_rdap_org
        self.host_resolver = host_resolver
        self.on_rate_limit: Callable[[str, float | None], None] | None = None

    @staticmethod
    def _parse_json_safe(response: httpx.Response) -> dict[str, Any] | None:
        content_type = (response.headers.get("content-type") or "").lower()
        text = response.text.lstrip()
        if "json" not in content_type and not text.startswith("{"):
            return None
        try:
            value = response.json()
        except (ValueError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _error_text(data: dict[str, Any] | None, response: httpx.Response) -> str:
        if data is None:
            return str(response.text).strip().lower()
        parts: list[str] = []
        for key in ("title", "detail", "description", "error", "message"):
            value = data.get(key)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(item for item in value if isinstance(item, str))
        return " ".join(parts).lower()

    @staticmethod
    def _reserved_or_blocked(text: str) -> bool:
        return any(
            marker in text
            for marker in ("reserved", "blocked", "prohibited", "not available for registration")
        )

    @staticmethod
    def _is_not_found(data: dict[str, Any] | None, text: str) -> bool:
        if data is not None and data.get("errorCode") == 404:
            return True
        return any(
            marker in text for marker in ("not found", "object does not exist", "does not exist")
        )

    @staticmethod
    def _is_no_service_error(text: str) -> bool:
        return any(
            marker in text
            for marker in ("no rdap service", "service not registered", "no service registered")
        )

    @staticmethod
    def _is_domain_object(data: dict[str, Any], domain: str) -> bool:
        if data.get("objectClassName") != "domain":
            return False
        name = str(data.get("ldhName") or data.get("unicodeName") or "").lower().rstrip(".")
        return bool(name) and name == domain.lower().rstrip(".")

    def get_authoritative_base_urls(self, domain: str) -> tuple[str, ...] | None:
        urls = self._bootstrap.get_base_urls_for_domain(domain)
        if urls:
            return urls
        if self._fallback_to_rdap_org:
            return ("https://rdap.org/",)
        return None

    def get_rdap_host(self, domain: str) -> str | None:
        urls = self.get_authoritative_base_urls(domain)
        return urlparse(urls[0]).hostname if urls else None

    @staticmethod
    def _result(
        domain: str,
        status: DomainCheckStatus,
        started: float,
        retries: int,
        detail: str | None = None,
    ) -> DomainCheckResult:
        return DomainCheckResult(
            domain=domain,
            status=status,
            source="rdap",
            checked_at=time.time(),
            detail=detail,
            latency_ms=(time.monotonic() - started) * 1000,
            retries=retries,
        )

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None = None) -> None:
        delay = min(1.0, 0.05 * (2 ** (attempt - 1)))
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), 5.0))
            except ValueError:
                pass
        time.sleep(delay)

    def check_domain(self, domain: str) -> DomainCheckResult:
        """Return a definitive or explicitly inconclusive RDAP result."""
        normalized = domain.strip().lower().rstrip(".")
        started = time.monotonic()
        base_urls = self.get_authoritative_base_urls(normalized)
        if not base_urls:
            return self._result(
                normalized,
                DomainCheckStatus.UNSUPPORTED,
                started,
                0,
                "No authoritative RDAP service found for TLD",
            )

        client = self._http_client or httpx.Client(timeout=self.timeout, follow_redirects=True)
        owns_client = self._http_client is None
        try:
            for attempt in range(1, self.max_retries + 1):
                base_url = base_urls[(attempt - 1) % len(base_urls)]
                parsed_base = urlparse(base_url)
                host = parsed_base.hostname
                if self.host_resolver is not None and host:
                    resolution = self.host_resolver(host)
                    if not resolution.resolved:
                        return self._result(
                            normalized,
                            DomainCheckStatus.NETWORK_ERROR,
                            started,
                            attempt - 1,
                            resolution.detail or "registry DNS resolution failed",
                        )
                url = base_url.rstrip("/") + "/domain/" + quote(normalized, safe=".-")
                try:
                    response = client.get(
                        url,
                        headers={
                            "Accept": "application/rdap+json, application/json",
                            "User-Agent": "domain-finder/2",
                        },
                        timeout=self.timeout,
                    )
                except httpx.TimeoutException as exc:
                    if attempt < self.max_retries:
                        self._backoff(attempt)
                        continue
                    return self._result(
                        normalized, DomainCheckStatus.NETWORK_ERROR, started, attempt - 1, str(exc)
                    )
                except httpx.HTTPError as exc:
                    if attempt < self.max_retries:
                        self._backoff(attempt)
                        continue
                    return self._result(
                        normalized, DomainCheckStatus.NETWORK_ERROR, started, attempt - 1, str(exc)
                    )

                data = self._parse_json_safe(response)
                status_code = response.status_code
                error_text = self._error_text(data, response)

                if status_code == 200:
                    if data is not None and self._is_domain_object(data, normalized):
                        return self._result(
                            normalized, DomainCheckStatus.REGISTERED, started, attempt - 1
                        )
                    return self._result(
                        normalized,
                        DomainCheckStatus.UNKNOWN,
                        started,
                        attempt - 1,
                        "RDAP returned 200 without a matching domain object",
                    )

                if status_code == 404:
                    if self._reserved_or_blocked(error_text):
                        return self._result(
                            normalized,
                            DomainCheckStatus.REGISTERED,
                            started,
                            attempt - 1,
                            error_text,
                        )
                    if self._is_no_service_error(error_text):
                        return self._result(
                            normalized, DomainCheckStatus.UNKNOWN, started, attempt - 1, error_text
                        )
                    # The URL comes from IANA's authoritative bootstrap. IANA's
                    # RDAP conformance test treats a 4xx response here as the
                    # expected signal for a non-existent domain object.
                    return self._result(
                        normalized, DomainCheckStatus.AVAILABLE, started, attempt - 1
                    )

                quota_limited = status_code == 403 and any(
                    marker in error_text
                    for marker in (
                        "allowed queries exceeded",
                        "query limit exceeded",
                        "too many queries",
                        "rate limit",
                        "rate-limit",
                    )
                )
                if status_code == 429 or quota_limited:
                    retry_after_header = response.headers.get("Retry-After")
                    retry_after_seconds: float | None = None
                    if retry_after_header:
                        try:
                            retry_after_seconds = float(retry_after_header)
                        except ValueError:
                            pass
                    if self.on_rate_limit is not None:
                        self.on_rate_limit(host or parsed_base.netloc, retry_after_seconds)
                    # HTTP 429 is an explicit inconclusive signal. Retrying the
                    # same request inside this worker just occupies the registry
                    # slot; let the checker fall back and pace future requests.
                    return self._result(
                        normalized, DomainCheckStatus.RATE_LIMITED, started, attempt - 1, error_text
                    )

                if status_code in RETRYABLE_STATUSES:
                    if attempt < self.max_retries:
                        self._backoff(attempt, response.headers.get("Retry-After"))
                        continue
                    return self._result(
                        normalized,
                        DomainCheckStatus.NETWORK_ERROR,
                        started,
                        attempt - 1,
                        f"RDAP server returned HTTP {status_code}",
                    )

                if status_code in (400, 422):
                    return self._result(
                        normalized, DomainCheckStatus.INVALID, started, attempt - 1, error_text
                    )
                if status_code in (501, 505):
                    return self._result(
                        normalized, DomainCheckStatus.UNSUPPORTED, started, attempt - 1, error_text
                    )
                return self._result(
                    normalized,
                    DomainCheckStatus.UNKNOWN,
                    started,
                    attempt - 1,
                    error_text or f"Unexpected RDAP HTTP {status_code}",
                )
        finally:
            if owns_client:
                client.close()

        return self._result(normalized, DomainCheckStatus.UNKNOWN, started, self.max_retries - 1)
