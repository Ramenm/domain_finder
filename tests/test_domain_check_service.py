"""Tests for DomainCheckService with caching."""

from __future__ import annotations

import time

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.domain.ports import DomainCheckerPort, ResultRepositoryPort
from domain_finder.domain.services import DomainCheckService
from domain_finder.infrastructure.cache import CacheManager


class MockDomainChecker(DomainCheckerPort):
    """Mock domain checker for testing."""

    def __init__(self, results: dict[str, DomainCheckResult] | None = None) -> None:
        """Initialize mock checker with predefined results."""
        self.results = results or {}
        self.checked_domains: list[str] = []

    def check_domain(self, domain: str) -> DomainCheckResult:
        """Check single domain."""
        self.checked_domains.append(domain)
        if domain in self.results:
            return self.results[domain]
        # Default: mark as unavailable
        return DomainCheckResult(
            domain=domain,
            available=False,
            source="rdap",
            checked_at=time.time(),
        )

    def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        """Check multiple domains."""
        results = {}
        for domain in domains:
            self.checked_domains.append(domain)
            if domain in self.results:
                results[domain] = self.results[domain]
            else:
                results[domain] = DomainCheckResult(
                    domain=domain,
                    available=False,
                    source="rdap",
                    checked_at=time.time(),
                )
        return results


class MockRepository(ResultRepositoryPort):
    """Mock repository for testing."""

    def __init__(self) -> None:
        """Initialize mock repository."""
        self.cache: dict[str, DomainCheckResult] = {}

    def get_cached_result(self, domain: str) -> DomainCheckResult | None:
        """Get cached result."""
        return self.cache.get(domain)

    def cache_result(self, result: DomainCheckResult) -> None:
        """Cache result."""
        self.cache[result.domain] = result

    def save_available_domains(self, domains: list[DomainCheckResult]) -> None:
        """Save available domains."""
        for result in domains:
            if result.available:
                self.cache_result(result)

    def clear(self) -> None:
        """Clear cache."""
        self.cache.clear()

    def known(self) -> dict[str, DomainCheckResult]:
        """Get all known results."""
        return self.cache.copy()


class TestDomainCheckService:
    """Tests for DomainCheckService with caching."""

    def test_check_domains_with_cache_hit(self):
        """Test that cached results are returned without calling checker."""
        # Setup: create cached result
        cached_result = DomainCheckResult(
            domain="cached.com",
            available=True,
            source="rdap",
            checked_at=time.time() - 100,
        )

        repository = MockRepository()
        repository.cache_result(cached_result)

        checker = MockDomainChecker()
        service = DomainCheckService(checker, repository)

        # Check domain that is cached
        results = service.check_domains_with_cache(["cached.com"])

        # Should return cached result
        assert len(results) == 1
        assert "cached.com" in results
        assert results["cached.com"].domain == "cached.com"
        assert results["cached.com"].available is True
        assert results["cached.com"].checked_at == cached_result.checked_at

        # Checker should not be called
        assert len(checker.checked_domains) == 0

    def test_check_domains_with_cache_miss(self):
        """Test that uncached domains are checked and cached."""
        repository = MockRepository()
        fresh_result = DomainCheckResult(
            domain="fresh.com",
            available=True,
            source="rdap",
            checked_at=time.time(),
        )
        checker = MockDomainChecker(results={"fresh.com": fresh_result})
        service = DomainCheckService(checker, repository)

        # Check uncached domain
        results = service.check_domains_with_cache(["fresh.com"])

        # Should return fresh result
        assert len(results) == 1
        assert "fresh.com" in results
        assert results["fresh.com"].available is True

        # Should be cached
        cached = repository.get_cached_result("fresh.com")
        assert cached is not None
        assert cached.domain == "fresh.com"
        assert cached.available is True

        # Checker should be called
        assert "fresh.com" in checker.checked_domains

    def test_check_domains_mixed_cache_hit_and_miss(self):
        """Test checking mix of cached and uncached domains."""
        # Setup: cache one domain
        cached_result = DomainCheckResult(
            domain="cached.com",
            available=False,
            source="whois",
            checked_at=time.time() - 50,
        )
        repository = MockRepository()
        repository.cache_result(cached_result)

        # Setup: fresh result for uncached domain
        fresh_result = DomainCheckResult(
            domain="fresh.com",
            available=True,
            source="rdap",
            checked_at=time.time(),
        )
        checker = MockDomainChecker(results={"fresh.com": fresh_result})
        service = DomainCheckService(checker, repository)

        # Check both domains
        results = service.check_domains_with_cache(["cached.com", "fresh.com"])

        # Should return both results
        assert len(results) == 2
        assert "cached.com" in results
        assert "fresh.com" in results

        # Cached domain should use cached result
        assert results["cached.com"].checked_at == cached_result.checked_at
        assert results["cached.com"].source == "whois"

        # Fresh domain should be checked and cached
        assert results["fresh.com"].available is True
        assert "fresh.com" in repository.cache

        # Checker should only be called for fresh domain
        assert "cached.com" not in checker.checked_domains
        assert "fresh.com" in checker.checked_domains

    def test_check_domains_passes_unknown_result_to_ttl_cache(self):
        """Transient results are cached briefly by TTL-aware repositories."""
        repository = MockRepository()
        # Simulate error result (marked as unavailable with unknown source)
        error_result = DomainCheckResult(
            domain="error.com",
            available=False,
            source="unknown",
            checked_at=time.time(),
        )
        checker = MockDomainChecker(results={"error.com": error_result})
        service = DomainCheckService(checker, repository)

        # Check domain
        results = service.check_domains_with_cache(["error.com"])

        # Should return result
        assert len(results) == 1
        assert "error.com" in results
        assert results["error.com"].source == "unknown"

        # Repository decides the short TTL for inconclusive results.
        cached = repository.get_cached_result("error.com")
        assert cached is not None
        assert cached.available is None

    def test_check_domains_caches_successful_results(self):
        """Test that successful results (rdap/whois) are cached."""
        repository = MockRepository()
        rdap_result = DomainCheckResult(
            domain="rdap.com",
            available=True,
            source="rdap",
            checked_at=time.time(),
        )
        whois_result = DomainCheckResult(
            domain="whois.com",
            available=False,
            source="whois",
            checked_at=time.time(),
        )
        checker = MockDomainChecker(
            results={
                "rdap.com": rdap_result,
                "whois.com": whois_result,
            }
        )
        service = DomainCheckService(checker, repository)

        # Check domains
        service.check_domains_with_cache(["rdap.com", "whois.com"])

        # Both should be cached
        assert repository.get_cached_result("rdap.com") is not None
        assert repository.get_cached_result("whois.com") is not None

    def test_check_domains_handles_checker_exception(self):
        """Test that checker exceptions are handled gracefully."""
        repository = MockRepository()

        # Create checker that raises exception
        class FailingChecker(DomainCheckerPort):
            def check_domain(self, domain: str) -> DomainCheckResult:
                raise Exception("Checker failed")

            def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
                raise Exception("Checker failed")

        checker = FailingChecker()
        service = DomainCheckService(checker, repository)

        # Check domains - should handle exception
        results = service.check_domains_with_cache(["failing.com"])

        # Failure is inconclusive, not proof that the domain is registered.
        assert len(results) == 1
        assert "failing.com" in results
        assert results["failing.com"].available is None
        assert results["failing.com"].status is DomainCheckStatus.UNKNOWN
        assert results["failing.com"].source == "unknown"

        # Should NOT be cached (error state)
        assert repository.get_cached_result("failing.com") is None

    def test_check_domains_with_real_cache_manager(self, tmp_path):
        """Test with real CacheManager implementation."""
        cache_file = tmp_path / "test_cache.json"
        repository = CacheManager(str(cache_file))

        fresh_result = DomainCheckResult(
            domain="test.com",
            available=True,
            source="rdap",
            checked_at=time.time(),
        )
        checker = MockDomainChecker(results={"test.com": fresh_result})
        service = DomainCheckService(checker, repository)

        # Check domain
        results = service.check_domains_with_cache(["test.com"])

        # Should be cached
        assert len(results) == 1
        assert results["test.com"].available is True

        # Save cache explicitly (DomainCheckService doesn't save, use case does)
        repository.save()

        # Reload cache and verify persistence
        repository2 = CacheManager(str(cache_file))
        cached = repository2.get_cached_result("test.com")
        assert cached is not None
        assert cached.domain == "test.com"
        assert cached.available is True

    def test_check_domains_multiple_iterations(self):
        """Test that repeated checks use cache."""
        repository = MockRepository()
        fresh_result = DomainCheckResult(
            domain="repeat.com",
            available=True,
            source="rdap",
            checked_at=time.time(),
        )
        checker = MockDomainChecker(results={"repeat.com": fresh_result})
        service = DomainCheckService(checker, repository)

        # First check - should call checker
        results1 = service.check_domains_with_cache(["repeat.com"])
        assert len(results1) == 1
        assert len(checker.checked_domains) == 1

        # Second check - should use cache
        results2 = service.check_domains_with_cache(["repeat.com"])
        assert len(results2) == 1
        assert len(checker.checked_domains) == 1  # Still 1, not 2

        # Results should be identical
        assert results1["repeat.com"].checked_at == results2["repeat.com"].checked_at
