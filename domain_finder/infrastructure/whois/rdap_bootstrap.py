"""IANA DNS RDAP bootstrap resolution with a small disk cache."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx

IANA_DNS_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"


class RdapBootstrap:
    """Resolve authoritative RDAP base URLs for DNS top-level domains."""

    def __init__(
        self,
        cache_path: str | Path = ".rdap_dns_bootstrap.json",
        ttl_seconds: float = 7 * 24 * 60 * 60,
        http_client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.ttl_seconds = ttl_seconds
        self.timeout = timeout
        self._http_client = http_client
        self._lock = threading.RLock()
        self._services: dict[str, tuple[str, ...]] = {}
        self._loaded_at = 0.0
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            services = payload.get("services", {})
            if isinstance(services, dict):
                self._services = {
                    str(tld).lower().lstrip("."): tuple(str(url) for url in urls)
                    for tld, urls in services.items()
                    if isinstance(urls, list)
                }
            self._loaded_at = float(payload.get("loaded_at", 0.0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._services = {}
            self._loaded_at = 0.0

    def _is_stale(self) -> bool:
        return not self._services or (time.time() - self._loaded_at) > self.ttl_seconds

    def _save_to_disk(self) -> None:
        payload = {
            "loaded_at": self._loaded_at,
            "services": {key: list(value) for key, value in self._services.items()},
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.cache_path)

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and not self._is_stale():
                return

            client = self._http_client or httpx.Client(timeout=self.timeout, follow_redirects=True)
            owns_client = self._http_client is None
            try:
                response = client.get(
                    IANA_DNS_BOOTSTRAP_URL,
                    headers={"Accept": "application/json"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                services: dict[str, tuple[str, ...]] = {}
                for entry in payload.get("services", []):
                    if not isinstance(entry, list) or len(entry) != 2:
                        continue
                    tlds, urls = entry
                    if not isinstance(tlds, list) or not isinstance(urls, list):
                        continue
                    normalized_urls = tuple(
                        url.rstrip("/") + "/" for url in urls if isinstance(url, str) and url
                    )
                    if not normalized_urls:
                        continue
                    for tld in tlds:
                        if isinstance(tld, str) and tld:
                            services[tld.lower().lstrip(".")] = normalized_urls
                if services:
                    self._services = services
                    self._loaded_at = time.time()
                    self._save_to_disk()
            finally:
                if owns_client:
                    client.close()

    def get_base_urls_for_tld(self, tld: str) -> tuple[str, ...] | None:
        normalized = tld.strip().lower().lstrip(".")
        if not normalized:
            return None
        with self._lock:
            if self._is_stale():
                try:
                    self.refresh()
                except (httpx.HTTPError, ValueError, TypeError, OSError):
                    if not self._services:
                        return None
            return self._services.get(normalized)

    def get_base_urls_for_domain(self, domain: str) -> tuple[str, ...] | None:
        normalized = domain.strip().lower().rstrip(".")
        if "." not in normalized:
            return None
        return self.get_base_urls_for_tld(normalized.rsplit(".", 1)[-1])
