"""Combined authoritative RDAP checker with conservative WHOIS fallback."""

from __future__ import annotations

import concurrent.futures
import threading
import time
from collections import deque
from contextlib import nullcontext

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TimeElapsedColumn, TimeRemainingColumn

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.domain.ports import DomainCheckerPort
from domain_finder.infrastructure.dns_prefilter import DnsPrefilter
from domain_finder.infrastructure.whois.host_limiter import PerHostLimiter
from domain_finder.infrastructure.whois.rdap_bootstrap import RdapBootstrap
from domain_finder.infrastructure.whois.rdap_client import RdapClient
from domain_finder.infrastructure.whois.registry_dns import RegistryDnsResolver
from domain_finder.infrastructure.whois.registry_profiles import RegistryProfileStore
from domain_finder.infrastructure.whois.reserved_policy import ReservedNamePolicy
from domain_finder.infrastructure.whois.whois_client import WhoisClient

console = Console()


_registry_dns = RegistryDnsResolver(timeout=1.5)


def _registry_backend_key(host: str) -> str:
    return _registry_dns.resolve(host).backend_key


class DomainChecker(DomainCheckerPort):
    """Check domains while keeping transport errors distinct from registry state."""

    def __init__(
        self,
        prefer_rdap: bool = True,
        whois_fallback: bool = True,
        max_workers: int = 20,
        rdap_timeout: float = 10.0,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        rdap_per_host: int = 6,
        whois_global_limit: int = 4,
        whois_verify: bool = False,
        dns_prefilter: bool = False,
        dns_fallback: bool = True,
        max_retries: int = 3,
        bootstrap_cache_file: str = ".rdap_dns_bootstrap.json",
        registry_profile_file: str | None = None,
        profile_store: RegistryProfileStore | None = None,
        reserved_names_cache_file: str = ".icann_reserved_names.xml",
        reserved_policy: ReservedNamePolicy | None = None,
    ) -> None:
        self.prefer_rdap = prefer_rdap
        self.whois_fallback = whois_fallback
        self.whois_verify = whois_verify
        self.dns_prefilter_enabled = dns_prefilter
        self.dns_fallback_enabled = dns_fallback
        self.dns_prefilter = (
            DnsPrefilter(timeout=min(2.0, rdap_timeout))
            if (dns_prefilter or dns_fallback)
            else None
        )
        self.max_workers = max_workers
        self._owns_profile_store = False
        self.profile_store: RegistryProfileStore | None
        if profile_store is not None:
            self.profile_store = profile_store
        elif registry_profile_file:
            self.profile_store = RegistryProfileStore(registry_profile_file)
            self._owns_profile_store = True
        else:
            self.profile_store = None

        try:
            import h2  # noqa: F401

            http2 = True
        except ImportError:
            http2 = False

        self._http_client = httpx.Client(
            timeout=rdap_timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            http2=http2,
        )
        self.reserved_policy = reserved_policy or ReservedNamePolicy(
            cache_path=reserved_names_cache_file,
            http_client=self._http_client,
        )
        bootstrap = RdapBootstrap(
            cache_path=bootstrap_cache_file,
            http_client=self._http_client,
            timeout=rdap_timeout,
        )
        self.rdap_client = RdapClient(
            timeout=rdap_timeout,
            max_retries=max_retries,
            http_client=self._http_client,
            bootstrap=bootstrap,
            host_resolver=_registry_dns.resolve,
        )
        self.whois_client = WhoisClient(raw_fallback=True, profile_store=self.profile_store)
        self._rdap_limiter = PerHostLimiter(per_host=rdap_per_host, global_limit=max_workers)
        self.rdap_client.on_rate_limit = lambda host, retry_after=None: self._rdap_limiter.penalize(
            _registry_backend_key(host), retry_after
        )
        self._whois_sem = threading.BoundedSemaphore(max(1, whois_global_limit))

    def close(self) -> None:
        """Close pooled network resources owned by this checker."""
        self._http_client.close()
        if self._owns_profile_store and self.profile_store is not None:
            self.profile_store.close()
            self._owns_profile_store = False

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _whois_checked(self, domain: str) -> DomainCheckResult:
        with self._whois_sem:
            return self.whois_client.check_domain(domain)

    def _rdap_checked(self, domain: str) -> DomainCheckResult:
        host_getter = getattr(self.rdap_client, "get_rdap_host", None)
        host = host_getter(domain) if callable(host_getter) else None
        limit_key = _registry_backend_key(host) if host else None
        guard = self._rdap_limiter.acquire(limit_key) if limit_key else nullcontext()
        with guard:
            result = self.rdap_client.check_domain(domain)
        if self.profile_store is not None:
            try:
                tld = (
                    domain.strip()
                    .lower()
                    .rstrip(".")
                    .encode("idna")
                    .decode("ascii")
                    .rsplit(".", 1)[-1]
                )
                self.profile_store.record_routing(tld, rdap_host=host, backend_key=limit_key)
                status = result.status or DomainCheckStatus.UNKNOWN
                self.profile_store.record_observation(tld, "rdap", status, result.latency_ms)
            except (UnicodeError, ValueError):
                pass
        if limit_key:
            if result.status is DomainCheckStatus.RATE_LIMITED:
                if not callable(getattr(self.rdap_client, "on_rate_limit", None)):
                    self._rdap_limiter.penalize(limit_key)
            elif result.is_definitive:
                self._rdap_limiter.reward(limit_key)
        return result

    @staticmethod
    def _network_error(domain: str, source: str, exc: Exception) -> DomainCheckResult:
        return DomainCheckResult(
            domain=domain,
            status=DomainCheckStatus.NETWORK_ERROR,
            source=source,
            checked_at=time.time(),
            detail=str(exc),
        )

    def _apply_reserved_policy(self, result: DomainCheckResult) -> DomainCheckResult:
        """Let explicit registry policy override absence/registrability evidence."""
        if result.status not in {
            DomainCheckStatus.UNREGISTERED,
            DomainCheckStatus.REGISTRABLE,
        }:
            return result
        try:
            match = self.reserved_policy.match(result.domain)
        except Exception:  # noqa: BLE001
            return result
        if match is None:
            return result
        return DomainCheckResult(
            domain=result.domain,
            status=DomainCheckStatus.RESERVED,
            source="policy",
            checked_at=time.time(),
            detail=match.detail,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    def _whois_supports_availability(self, domain: str) -> bool:
        checker = getattr(self.whois_client, "supports_availability", None)
        return bool(checker(domain)) if callable(checker) else True

    def _late_dns_registered(self, domain: str) -> DomainCheckResult | None:
        """Use DNS only as a final proof of registration, never of availability."""
        if not self.dns_fallback_enabled or self.dns_prefilter is None:
            return None
        try:
            has_ns = self.dns_prefilter.has_nameservers(domain)
        except Exception:  # noqa: BLE001
            return None
        if has_ns is not True:
            return None
        return DomainCheckResult(
            domain=domain,
            status=DomainCheckStatus.REGISTERED,
            source="dns",
            checked_at=time.time(),
            detail="NS records present (late fallback)",
        )

    def check_domain(self, domain: str) -> DomainCheckResult:
        """Check one domain using safe DNS proof, then RDAP/WHOIS."""
        if self.dns_prefilter_enabled and self.dns_prefilter is not None:
            if self.dns_prefilter.has_nameservers(domain) is True:
                return DomainCheckResult(
                    domain=domain,
                    status=DomainCheckStatus.REGISTERED,
                    source="dns",
                    checked_at=time.time(),
                    detail="NS records present",
                )

        if not self.prefer_rdap:
            try:
                return self._apply_reserved_policy(self._whois_checked(domain))
            except Exception as exc:  # noqa: BLE001
                return self._network_error(domain, "whois", exc)

        if self.whois_fallback:
            host_getter = getattr(self.rdap_client, "get_rdap_host", None)
            host = host_getter(domain) if callable(host_getter) else None
            is_throttled = getattr(self._rdap_limiter, "is_throttled", None)
            limit_key = _registry_backend_key(host) if host else None
            if limit_key and callable(is_throttled) and is_throttled(limit_key):
                dns_result = self._late_dns_registered(domain)
                if dns_result is not None:
                    return dns_result
                if self._whois_supports_availability(domain):
                    try:
                        whois_fast = self._whois_checked(domain)
                    except Exception:  # noqa: BLE001
                        whois_fast = None
                    if whois_fast is not None and whois_fast.is_definitive:
                        return self._apply_reserved_policy(whois_fast)

        try:
            rdap_result = self._rdap_checked(domain)
        except Exception as exc:  # noqa: BLE001
            rdap_result = self._network_error(domain, "rdap", exc)

        rdap_result = self._apply_reserved_policy(rdap_result)

        if rdap_result.is_definitive and not self.whois_verify:
            return rdap_result

        if not rdap_result.is_definitive:
            dns_result = self._late_dns_registered(domain)
            if dns_result is not None:
                return dns_result

        should_try_whois = self.whois_verify or (
            self.whois_fallback
            and not rdap_result.is_definitive
            and self._whois_supports_availability(domain)
        )
        if not should_try_whois:
            return self._late_dns_registered(domain) or rdap_result

        try:
            whois_result = self._apply_reserved_policy(self._whois_checked(domain))
        except Exception:  # noqa: BLE001
            return self._late_dns_registered(domain) or rdap_result

        if whois_result.is_definitive:
            if not rdap_result.is_definitive:
                return whois_result
            if whois_result.status is DomainCheckStatus.REGISTERED:
                return whois_result
        return self._late_dns_registered(domain) or rdap_result

    def _routing_key(self, domain: str) -> str:
        host_getter = getattr(self.rdap_client, "get_rdap_host", None)
        host = host_getter(domain) if callable(host_getter) else None
        if host:
            return f"rdap:{_registry_backend_key(host)}"
        try:
            tld = (
                domain.strip().lower().rstrip(".").encode("idna").decode("ascii").rsplit(".", 1)[-1]
            )
        except UnicodeError:
            tld = domain.rsplit(".", 1)[-1].lower()
        return f"whois:{tld}"

    def _interleave_by_registry(self, domains: list[str]) -> list[str]:
        """Round-robin backends so one throttled registry cannot starve the batch."""
        groups: dict[str, deque[str]] = {}
        for domain in domains:
            groups.setdefault(self._routing_key(domain), deque()).append(domain)
        active = deque(groups)
        ordered: list[str] = []
        while active:
            key = active.popleft()
            ordered.append(groups[key].popleft())
            if groups[key]:
                active.append(key)
        return ordered

    def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        """Check a deduplicated batch concurrently."""
        unique_domains = list(dict.fromkeys(domains))
        scheduled_domains = self._interleave_by_registry(unique_domains)
        results: dict[str, DomainCheckResult] = {}

        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool,
            Progress(
                SpinnerColumn(),
                "[progress.description]{task.description}",
                BarColumn(),
                "{task.completed}/{task.total}",
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                transient=True,
                console=console,
            ) as progress,
        ):
            task = progress.add_task("[cyan]Checking domains...[/cyan]", total=len(unique_domains))
            futures = {
                pool.submit(self.check_domain, domain): domain for domain in scheduled_domains
            }
            for future in concurrent.futures.as_completed(futures):
                domain = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = DomainCheckResult(
                        domain=domain,
                        status=DomainCheckStatus.UNKNOWN,
                        source="unknown",
                        checked_at=time.time(),
                        detail=str(exc),
                    )
                results[domain] = result
                progress.advance(task)
        return results
