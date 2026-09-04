from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import dns.exception
import dns.resolver


@dataclass(frozen=True)
class RegistryHostResolution:
    """Bounded DNS result used only for RDAP transport routing."""

    backend_key: str
    resolved: bool
    detail: str | None = None


SYSTEMD_UPSTREAM_RESOLV_CONF = Path("/run/systemd/resolve/resolv.conf")


def _default_resolver():
    if SYSTEMD_UPSTREAM_RESOLV_CONF.exists():
        return dns.resolver.Resolver(filename=str(SYSTEMD_UPSTREAM_RESOLV_CONF))
    return dns.resolver.Resolver()


class RegistryDnsResolver:
    """Resolve RDAP host aliases without unbounded system getaddrinfo calls."""

    def __init__(
        self,
        timeout: float = 0.75,
        resolver=None,
        success_ttl: float = 60 * 60,
        failure_ttl: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout = max(0.05, timeout)
        self.success_ttl = max(0.0, success_ttl)
        self.failure_ttl = max(0.0, failure_ttl)
        self.resolver = resolver or _default_resolver()
        self._clock = clock
        self._cache: dict[str, tuple[float, RegistryHostResolution]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _normalize(host: str) -> str:
        return host.strip().lower().rstrip(".")

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise dns.exception.Timeout(timeout=self.timeout)
        return max(0.01, remaining)

    def _query(self, host: str, qtype: str, deadline: float):
        return self.resolver.resolve(
            host,
            qtype,
            lifetime=self._remaining(deadline),
        )

    @staticmethod
    def _failure(host: str, exc: Exception) -> RegistryHostResolution:
        if isinstance(exc, dns.resolver.NXDOMAIN):
            detail = "registry DNS NXDOMAIN"
        elif isinstance(exc, dns.exception.Timeout):
            detail = "registry DNS timeout"
        else:
            detail = f"registry DNS failure: {exc}"
        return RegistryHostResolution(host, False, detail)

    def _resolve_uncached(self, host: str) -> RegistryHostResolution:
        deadline = self._clock() + self.timeout
        current = host
        try:
            for _ in range(5):
                try:
                    answer = self._query(current, "CNAME", deadline)
                except dns.resolver.NoAnswer:
                    break
                target = self._normalize(str(answer[0].target))
                if not target or target == current:
                    break
                current = target
            else:
                return RegistryHostResolution(current, False, "registry DNS CNAME loop/depth")

            try:
                answer = self._query(current, "A", deadline)
                if answer:
                    return RegistryHostResolution(current, True)
            except dns.resolver.NoAnswer:
                answer = self._query(current, "AAAA", deadline)
                if answer:
                    return RegistryHostResolution(current, True)
            return RegistryHostResolution(current, False, "registry DNS has no A/AAAA records")
        except (
            dns.resolver.NXDOMAIN,
            dns.exception.Timeout,
            dns.resolver.NoNameservers,
            OSError,
        ) as exc:
            return self._failure(current, exc)

    def resolve(self, host: str) -> RegistryHostResolution:
        normalized = self._normalize(host)
        if not normalized:
            return RegistryHostResolution("", False, "empty registry host")
        now = self._clock()
        with self._lock:
            cached = self._cache.get(normalized)
            if cached is not None:
                expires_at, value = cached
                if expires_at > now:
                    return value
                self._cache.pop(normalized, None)

        result = self._resolve_uncached(normalized)
        ttl = self.success_ttl if result.resolved else self.failure_ttl
        with self._lock:
            self._cache[normalized] = (self._clock() + ttl, result)
        return result
