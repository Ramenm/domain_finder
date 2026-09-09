"""Ports (interfaces) for domain layer - define contracts for adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import DomainCheckResult, DomainSearchParams


class DomainProviderPort(ABC):
    """Port for LLM providers that generate domain suggestions."""

    @abstractmethod
    def generate_domains(self, params: DomainSearchParams) -> str:
        """
        Generate domain suggestions using LLM.

        Args:
            params: Parameters for domain generation

        Returns:
            Raw text response from LLM containing domain suggestions

        Raises:
            ProviderError: If generation fails
        """
        pass


class DomainCheckerPort(ABC):
    """Port for checking domain availability."""

    @abstractmethod
    def check_domain(self, domain: str) -> DomainCheckResult:
        """
        Check if a domain is available.

        Args:
            domain: Domain name to check (e.g., 'example.com')

        Returns:
            DomainCheckResult with availability status

        Raises:
            DomainCheckError: If check fails
        """
        pass

    @abstractmethod
    def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        """
        Check multiple domains concurrently.

        Args:
            domains: List of domain names to check

        Returns:
            Dictionary mapping domain names to check results

        Raises:
            DomainCheckError: If check fails
        """
        pass


class ResultRepositoryPort(ABC):
    """Port for persisting domain search results."""

    @abstractmethod
    def save_available_domains(self, domains: list[DomainCheckResult]) -> None:
        """
        Save confirmed registrable domains to persistent storage.

        Args:
            domains: List of available domain check results
        """
        pass

    @abstractmethod
    def get_cached_result(self, domain: str) -> DomainCheckResult | None:
        """
        Get cached check result for a domain.

        Args:
            domain: Domain name to look up

        Returns:
            Cached result if exists, None otherwise
        """
        pass

    @abstractmethod
    def cache_result(self, result: DomainCheckResult) -> None:
        """
        Cache a domain check result.

        Args:
            result: Domain check result to cache
        """
        pass
