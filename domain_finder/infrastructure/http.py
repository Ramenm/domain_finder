"""HTTP client wrapper using httpx."""

from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

import httpx

from domain_finder.domain.errors import ProviderError


class HttpClient:
    """HTTP client with retry logic and rate limiting support."""

    def __init__(
        self,
        timeout: float = 60.0,
        retries: int = 3,
        backoff_min: float = 1.0,
        backoff_max: float = 3.0,
    ) -> None:
        """
        Initialize HTTP client.

        Args:
            timeout: Request timeout in seconds
            retries: Number of retry attempts
            backoff_min: Minimum backoff delay in seconds
            backoff_max: Maximum backoff delay in seconds
        """
        self.timeout = timeout
        self.retries = retries
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self._client: Optional[httpx.Client] = None

    def __enter__(self) -> HttpClient:
        """Enter context manager."""
        self._client = httpx.Client(timeout=self.timeout)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager."""
        if self._client:
            self._client.close()
            self._client = None

    def post(
        self,
        url: str,
        headers: Dict[str, str],
        json_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Make POST request with retry logic.

        Args:
            url: Request URL
            headers: Request headers
            json_data: JSON payload

        Returns:
            Response JSON data

        Raises:
            ProviderError: If request fails after retries
        """
        if not self._client:
            self._client = httpx.Client(timeout=self.timeout)

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self._client.post(url, headers=headers, json=json_data)
                if response.status_code == 429:
                    # Rate limited - backoff and retry
                    delay = random.uniform(self.backoff_min, self.backoff_max) * attempt
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code < 500:  # Don't retry client errors
                    raise ProviderError(f"HTTP {e.response.status_code}: {e.response.text}")
            except Exception as e:  # noqa: BLE001
                last_exc = e
                delay = random.uniform(self.backoff_min, self.backoff_max) * attempt
                time.sleep(delay)

        raise ProviderError(f"Request failed after {self.retries} attempts: {last_exc}")

    def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """
        Make GET request.

        Args:
            url: Request URL
            headers: Optional request headers

        Returns:
            HTTP response
        """
        if not self._client:
            self._client = httpx.Client(timeout=self.timeout)

        return self._client.get(url, headers=headers or {})

