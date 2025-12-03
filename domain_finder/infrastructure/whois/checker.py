"""Combined domain checker with RDAP and WHOIS support."""

from __future__ import annotations

import concurrent.futures
import time

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TimeElapsedColumn, TimeRemainingColumn

from domain_finder.domain.errors import DomainCheckError
from domain_finder.domain.models import DomainCheckResult
from domain_finder.domain.ports import DomainCheckerPort
from domain_finder.infrastructure.whois.rdap_client import RdapClient
from domain_finder.infrastructure.whois.whois_client import WhoisClient

console = Console()


class DomainChecker(DomainCheckerPort):
    """Domain checker with RDAP and WHOIS fallback support."""

    def __init__(
        self,
        prefer_rdap: bool = True,
        whois_fallback: bool = True,  # Enable fallback by default for reliability
        max_workers: int = 20,
        rdap_timeout: float = 10.0,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
    ) -> None:
        """
        Initialize domain checker.

        Args:
            prefer_rdap: Prefer RDAP over WHOIS
            whois_fallback: Use WHOIS as fallback if RDAP is uncertain
            max_workers: Maximum number of concurrent workers
            rdap_timeout: RDAP request timeout
            max_connections: Maximum connections in pool
            max_keepalive_connections: Maximum keepalive connections
        """
        self.prefer_rdap = prefer_rdap
        self.whois_fallback = whois_fallback
        self.max_workers = max_workers
        # Check if HTTP/2 is available
        try:
            import h2  # noqa: F401

            http2_enabled = True
        except ImportError:
            http2_enabled = False

        # Create shared HTTP client with connection pooling for RDAP
        self._http_client = httpx.Client(
            timeout=rdap_timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            http2=http2_enabled,  # Enable HTTP/2 only if h2 package is installed
        )
        self.rdap_client = RdapClient(
            timeout=rdap_timeout,
            max_retries=3,
            http_client=self._http_client,
        )
        self.whois_client = WhoisClient()

    def __del__(self) -> None:
        """Cleanup HTTP client on deletion."""
        if hasattr(self, "_http_client"):
            self._http_client.close()

    def check_domain(self, domain: str) -> DomainCheckResult:
        """
        Check single domain availability.

        Args:
            domain: Domain name to check

        Returns:
            DomainCheckResult with availability status
        """
        if self.prefer_rdap:
            try:
                result = self.rdap_client.check_domain(domain)

                # If fallback is enabled, always verify with WHOIS for accuracy
                if self.whois_fallback:
                    try:
                        whois_result = self.whois_client.check_domain(domain)
                        # If WHOIS says unavailable, trust it (more reliable for registered domains)
                        if not whois_result.available:
                            return whois_result
                        # If both say available, trust RDAP (faster and reliable for availability)
                        if result.available:
                            return result
                        # If RDAP says unavailable but WHOIS says available,
                        # trust WHOIS (rare case, but WHOIS might be more accurate)
                        return whois_result
                    except Exception:  # noqa: BLE001
                        # If WHOIS fails (timeout, etc.), trust RDAP result
                        return result

                # No fallback - return RDAP result
                return result
            except DomainCheckError:
                # If RDAP fails (timeout, service unavailable, etc.), use WHOIS fallback
                if self.whois_fallback:
                    return self.whois_client.check_domain(domain)
                # If no fallback, re-raise the error
                raise
        else:
            return self.whois_client.check_domain(domain)

    def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        """
        Check multiple domains concurrently.

        Args:
            domains: List of domain names to check

        Returns:
            Dictionary mapping domain names to check results
        """
        # Remove duplicates while preserving order
        unique_domains = list(dict.fromkeys(domains))
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
            futures = {pool.submit(self.check_domain, domain): domain for domain in unique_domains}

            for future in concurrent.futures.as_completed(futures):
                domain = futures[future]
                try:
                    result = future.result()
                    results[result.domain] = result
                except DomainCheckError:
                    # For domain check errors (timeouts, service unavailable),
                    # mark as unavailable to avoid false positives
                    results[domain] = DomainCheckResult(
                        domain=domain,
                        available=False,
                        source="unknown",
                        checked_at=time.time(),
                    )
                except Exception:  # noqa: BLE001
                    # On other errors, mark as unavailable
                    results[domain] = DomainCheckResult(
                        domain=domain,
                        available=False,
                        source="unknown",
                        checked_at=time.time(),
                    )
                finally:
                    progress.advance(task)

        return results
