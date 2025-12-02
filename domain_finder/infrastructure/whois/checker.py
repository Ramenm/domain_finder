"""Combined domain checker with RDAP and WHOIS support."""

from __future__ import annotations

import concurrent.futures
import time
from typing import List

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
        whois_fallback: bool = False,
        max_workers: int = 20,
        rdap_timeout: float = 10.0,
    ) -> None:
        """
        Initialize domain checker.

        Args:
            prefer_rdap: Prefer RDAP over WHOIS
            whois_fallback: Use WHOIS as fallback if RDAP is uncertain
            max_workers: Maximum number of concurrent workers
            rdap_timeout: RDAP request timeout
        """
        self.prefer_rdap = prefer_rdap
        self.whois_fallback = whois_fallback
        self.max_workers = max_workers
        self.rdap_client = RdapClient(timeout=rdap_timeout)
        self.whois_client = WhoisClient()

    def check_domain(self, domain: str) -> DomainCheckResult:
        """
        Check single domain availability.

        Args:
            domain: Domain name to check

        Returns:
            DomainCheckResult with availability status
        """
        if self.prefer_rdap:
            result = self.rdap_client.check_domain(domain)
            # If RDAP says unavailable and fallback is enabled, try WHOIS
            if not result.available and self.whois_fallback:
                whois_result = self.whois_client.check_domain(domain)
                return whois_result
            return result
        else:
            return self.whois_client.check_domain(domain)

    def check_domains(self, domains: List[str]) -> dict[str, DomainCheckResult]:
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool, Progress(
            SpinnerColumn(),
            "[progress.description]{task.description}",
            BarColumn(),
            "{task.completed}/{task.total}",
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=True,
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Проверка доменов...[/cyan]", total=len(unique_domains))
            futures = {pool.submit(self.check_domain, domain): domain for domain in unique_domains}

            for future in concurrent.futures.as_completed(futures):
                domain = futures[future]
                try:
                    result = future.result()
                    results[result.domain] = result
                except DomainCheckError as e:
                    # For domain check errors (timeouts, service unavailable), 
                    # mark as unavailable to avoid false positives
                    results[domain] = DomainCheckResult(
                        domain=domain,
                        available=False,
                        source="unknown",
                        checked_at=time.time(),
                    )
                except Exception as e:  # noqa: BLE001
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

