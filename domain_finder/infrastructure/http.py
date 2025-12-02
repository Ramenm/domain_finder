"""HTTP client wrapper using httpx."""

from __future__ import annotations

import json
import random
import threading
import time
from collections import deque
from typing import Any, Dict, Iterator, Optional

import httpx

from domain_finder.domain.errors import ProviderError

# Check if HTTP/2 is available
try:
    import h2  # noqa: F401
    HTTP2_AVAILABLE = True
except ImportError:
    HTTP2_AVAILABLE = False


class HttpClient:
    """HTTP client with retry logic, rate limiting, and connection pooling."""

    def __init__(
        self,
        timeout: float = 60.0,
        retries: int = 3,
        backoff_min: float = 1.0,
        backoff_max: float = 3.0,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        rate_limit_per_minute: Optional[int] = None,
    ) -> None:
        """
        Initialize HTTP client.

        Args:
            timeout: Request timeout in seconds
            retries: Number of retry attempts
            backoff_min: Minimum backoff delay in seconds
            backoff_max: Maximum backoff delay in seconds
            max_connections: Maximum number of connections in pool
            max_keepalive_connections: Maximum keepalive connections
            rate_limit_per_minute: Optional rate limit (requests per minute)
        """
        self.timeout = timeout
        self.retries = retries
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self._client: Optional[httpx.Client] = None
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        # Rate limiting
        self.rate_limit_per_minute = rate_limit_per_minute
        self._rate_limit_times: deque = deque()
        self._rate_limit_lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client with connection pooling."""
        if not self._client:
            self._client = httpx.Client(
                timeout=self.timeout,
                limits=self._limits,
                http2=HTTP2_AVAILABLE,  # Enable HTTP/2 only if h2 package is installed
            )
        return self._client

    def _wait_for_rate_limit(self) -> None:
        """Wait if rate limit would be exceeded."""
        if not self.rate_limit_per_minute:
            return

        now = time.time()
        with self._rate_limit_lock:
            # Remove timestamps older than 1 minute
            while self._rate_limit_times and self._rate_limit_times[0] < now - 60:
                self._rate_limit_times.popleft()

            # If at limit, wait until oldest request is 1 minute old
            if len(self._rate_limit_times) >= self.rate_limit_per_minute:
                wait_time = 60 - (now - self._rate_limit_times[0]) + 0.1
                if wait_time > 0:
                    time.sleep(wait_time)
                    # Recalculate after wait
                    now = time.time()
                    while self._rate_limit_times and self._rate_limit_times[0] < now - 60:
                        self._rate_limit_times.popleft()

            # Record this request
            self._rate_limit_times.append(now)

    def __enter__(self) -> HttpClient:
        """Enter context manager."""
        self._get_client()
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
        client = self._get_client()

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                # Apply rate limiting
                self._wait_for_rate_limit()
                response = client.post(url, headers=headers, json=json_data)
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
                    raise ProviderError(
                        f"HTTP-ошибка {e.response.status_code}: {e.response.text[:200]}"
                    )
            except Exception as e:  # noqa: BLE001
                last_exc = e
                delay = random.uniform(self.backoff_min, self.backoff_max) * attempt
                time.sleep(delay)

        raise ProviderError(
            f"Запрос не выполнен после {self.retries} попыток: {last_exc}"
        )

    def post_stream(
        self,
        url: str,
        headers: Dict[str, str],
        json_data: Dict[str, Any],
    ) -> Iterator[Dict[str, Any]]:
        """
        Make streaming POST request for LLM streaming responses.

        Args:
            url: Request URL
            headers: Request headers
            json_data: JSON payload (should include "stream": True)

        Yields:
            JSON chunks from streaming response

        Raises:
            ProviderError: If request fails after retries
        """
        client = self._get_client()
        json_data = {**json_data, "stream": True}

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                # Apply rate limiting
                self._wait_for_rate_limit()
                with client.stream("POST", url, headers=headers, json=json_data) as response:
                    if response.status_code == 429:
                        delay = random.uniform(self.backoff_min, self.backoff_max) * attempt
                        time.sleep(delay)
                        continue
                    response.raise_for_status()

                    # Parse SSE (Server-Sent Events) format
                    for line in response.iter_lines():
                        if not line:
                            continue

                        # OpenAI-style: "data: {...}" or just JSON
                        if line.startswith("data: "):
                            line = line[len("data: "):]

                        if line.strip() == "[DONE]":
                            break

                        try:
                            chunk = json.loads(line)
                            yield chunk
                        except json.JSONDecodeError:
                            # Skip malformed chunks
                            continue

                    return  # Success, exit retry loop

            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code < 500:
                    raise ProviderError(
                        f"HTTP-ошибка {e.response.status_code}: {e.response.text[:200]}"
                    )
            except Exception as e:  # noqa: BLE001
                last_exc = e
                delay = random.uniform(self.backoff_min, self.backoff_max) * attempt
                time.sleep(delay)

        raise ProviderError(
            f"Стриминг-запрос не выполнен после {self.retries} попыток: {last_exc}"
        )

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
        client = self._get_client()
        return client.get(url, headers=headers or {})

    def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client:
            self._client.close()
            self._client = None

