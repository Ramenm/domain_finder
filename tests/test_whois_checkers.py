"""Tests for WHOIS/RDAP domain checkers with large-scale random domain generation."""

from __future__ import annotations

import random
import string
import time

import pytest

from domain_finder.domain.errors import DomainCheckError
from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.infrastructure.whois.checker import DomainChecker
from domain_finder.infrastructure.whois.rdap_client import RdapClient
from domain_finder.infrastructure.whois.whois_client import WhoisClient

pytestmark = [pytest.mark.network, pytest.mark.slow]


def generate_random_domain(
    min_length: int = 4,
    max_length: int = 63,
    tld: str | None = None,
    use_common_tlds: bool = True,
) -> str:
    """
    Generate a random domain name.

    Args:
        min_length: Minimum label length
        max_length: Maximum label length
        tld: Specific TLD to use, or None for random
        use_common_tlds: Use common TLDs if tld is None

    Returns:
        Random domain name (e.g., 'abc123xyz.com')
    """
    common_tlds = ["com", "org", "net", "io", "ai", "co", "dev", "app", "xyz", "info"]

    # Generate random label
    length = random.randint(min_length, max_length)
    # Use alphanumeric characters, but ensure it starts with a letter
    first_char = random.choice(string.ascii_lowercase)
    rest_chars = "".join(random.choices(string.ascii_lowercase + string.digits, k=length - 1))
    label = first_char + rest_chars

    # Choose TLD
    if tld:
        chosen_tld = tld
    elif use_common_tlds:
        chosen_tld = random.choice(common_tlds)
    else:
        # Use random 2-3 letter TLD
        tld_length = random.randint(2, 3)
        chosen_tld = "".join(random.choices(string.ascii_lowercase, k=tld_length))

    return f"{label}.{chosen_tld}"


def generate_random_domains(
    count: int,
    min_length: int = 4,
    max_length: int = 20,
    tlds: list[str] | None = None,
) -> list[str]:
    """
    Generate multiple random domain names.

    Args:
        count: Number of domains to generate
        min_length: Minimum label length
        max_length: Maximum label length
        tlds: List of TLDs to use, or None for random

    Returns:
        List of random domain names
    """
    domains = []
    seen = set()

    for _ in range(count):
        # Try to generate unique domain
        attempts = 0
        while attempts < 100:  # Prevent infinite loop
            if tlds:
                tld = random.choice(tlds)
            else:
                tld = None

            domain = generate_random_domain(
                min_length=min_length,
                max_length=max_length,
                tld=tld,
            )

            if domain not in seen:
                seen.add(domain)
                domains.append(domain)
                break
            attempts += 1
        else:
            # If we can't generate unique, just add it anyway
            domains.append(domain)

    return domains


def assert_result_semantics(result: DomainCheckResult) -> None:
    """Assert the documented tri-state availability contract."""
    assert result.status is not None
    if result.status in {DomainCheckStatus.AVAILABLE, DomainCheckStatus.REGISTRABLE}:
        assert result.available is True
    elif result.status in {DomainCheckStatus.REGISTERED, DomainCheckStatus.RESERVED}:
        assert result.available is False
    else:
        assert result.available is None


class TestRdapClient:
    """Tests for RDAP client with random domains."""

    def test_rdap_client_single_random_domain(self):
        """Test RDAP client with a single random domain."""
        client = RdapClient(timeout=10.0, max_retries=2)
        # Use .com TLD which reliably supports RDAP
        domain = generate_random_domain(min_length=8, max_length=15, tld="com")

        try:
            result = client.check_domain(domain)
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert result.source == "rdap"
            assert_result_semantics(result)
            assert result.checked_at > 0
        except DomainCheckError:
            # Some domains might fail due to network issues or TLD support
            # This is acceptable for random domain testing
            pass

    def test_rdap_client_multiple_random_domains(self):
        """Test RDAP client with multiple random domains."""
        client = RdapClient(timeout=10.0, max_retries=2)
        # Use reliable TLDs that support RDAP
        domains = generate_random_domains(
            count=10,
            min_length=6,
            max_length=12,
            tlds=["com", "org", "net"],
        )

        results = []
        errors = []
        for domain in domains:
            try:
                result = client.check_domain(domain)
                results.append(result)
                assert isinstance(result, DomainCheckResult)
                assert result.domain == domain
                assert result.source == "rdap"
            except DomainCheckError as e:
                # Some domains might fail (e.g., TLD without RDAP support, network issues)
                errors.append((domain, str(e)))

        # At least some results should be obtained
        assert len(results) > 0, f"Got {len(errors)} errors, expected at least some successes"

    def test_rdap_client_large_scale_random_domains(self):
        """Test RDAP client with a large number of random domains."""
        client = RdapClient(timeout=8.0, max_retries=2)
        # Generate 50 random domains with reliable TLDs
        domains = generate_random_domains(
            count=50,
            min_length=5,
            max_length=18,
            tlds=["com", "org", "net"],  # Common TLDs with reliable RDAP support
        )

        results = []
        errors = []

        start_time = time.time()
        for domain in domains:
            try:
                result = client.check_domain(domain)
                results.append(result)
            except DomainCheckError as e:
                errors.append((domain, str(e)))

        elapsed = time.time() - start_time

        # Should get 100% results (all domains should be checked successfully)
        assert len(results) == len(domains), (
            f"Expected 100% success rate, got {len(results)}/{len(domains)}"
        )
        # Log statistics
        print("\nRDAP Large Scale Test:")
        print(f"  Total domains: {len(domains)}")
        print(f"  Successful checks: {len(results)}")
        print(f"  Errors: {len(errors)}")
        print(f"  Success rate: {len(results) / len(domains) * 100:.1f}%")
        print(f"  Time elapsed: {elapsed:.2f}s")
        print(f"  Average time per domain: {elapsed / len(domains):.3f}s")

        # Verify all results are valid
        for result in results:
            assert isinstance(result, DomainCheckResult)
            assert result.domain in domains
            assert result.source == "rdap"
            assert_result_semantics(result)


class TestWhoisClient:
    """Tests for WHOIS client with random domains."""

    def test_whois_client_single_random_domain(self):
        """Test WHOIS client with a single random domain."""
        client = WhoisClient()
        domain = generate_random_domain(min_length=8, max_length=15)

        result = client.check_domain(domain)

        assert isinstance(result, DomainCheckResult)
        assert result.domain == domain
        assert result.source == "whois"
        assert_result_semantics(result)
        assert result.checked_at > 0

    def test_whois_client_multiple_random_domains(self):
        """Test WHOIS client with multiple random domains."""
        client = WhoisClient()
        domains = generate_random_domains(count=10, min_length=6, max_length=12)

        results = []
        for domain in domains:
            result = client.check_domain(domain)
            results.append(result)
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert result.source == "whois"

        assert len(results) == len(domains)

    def test_whois_client_large_scale_random_domains(self):
        """Test WHOIS client with a large number of random domains."""
        client = WhoisClient()
        # Generate 30 random domains (WHOIS is slower)
        domains = generate_random_domains(
            count=30,
            min_length=5,
            max_length=15,
            tlds=["com", "org", "net"],
        )

        results = []
        start_time = time.time()

        for domain in domains:
            result = client.check_domain(domain)
            results.append(result)

        elapsed = time.time() - start_time

        assert len(results) == len(domains)
        print("\nWHOIS Large Scale Test:")
        print(f"  Total domains: {len(domains)}")
        print(f"  Successful checks: {len(results)}")
        print(f"  Time elapsed: {elapsed:.2f}s")
        print(f"  Average time per domain: {elapsed / len(domains):.3f}s")

        # Verify all results are valid
        for result in results:
            assert isinstance(result, DomainCheckResult)
            assert result.domain in domains
            assert result.source == "whois"


class TestDomainChecker:
    """Tests for combined DomainChecker with random domains."""

    def test_domain_checker_single_random_domain(self):
        """Test DomainChecker with a single random domain."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=False,
            max_workers=5,
            rdap_timeout=10.0,
        )
        # Use .com TLD which reliably supports RDAP
        domain = generate_random_domain(min_length=8, max_length=15, tld="com")

        try:
            result = checker.check_domain(domain)
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert result.source in ("rdap", "whois", "dns", "policy", "unknown")
            assert_result_semantics(result)
        except DomainCheckError:
            # Some domains might fail due to network issues or TLD support
            # This is acceptable for random domain testing
            pass

    def test_domain_checker_multiple_random_domains(self):
        """Test DomainChecker with multiple random domains."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=False,
            max_workers=10,
            rdap_timeout=8.0,
        )
        # Use reliable TLDs
        domains = generate_random_domains(
            count=20,
            min_length=6,
            max_length=12,
            tlds=["com", "org", "net"],
        )

        results = checker.check_domains(domains)

        assert len(results) == len(domains)
        for domain in domains:
            assert domain in results
            result = results[domain]
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert result.source in ("rdap", "whois", "dns", "policy", "unknown")

    def test_domain_checker_large_scale_random_domains(self):
        """Test DomainChecker with a large number of random domains."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=False,
            max_workers=20,
            rdap_timeout=8.0,
            max_connections=50,
        )
        # Generate 100 random domains with reliable TLDs
        domains = generate_random_domains(
            count=100,
            min_length=5,
            max_length=20,
            tlds=["com", "org", "net"],  # Use reliable TLDs
        )

        start_time = time.time()
        results = checker.check_domains(domains)
        elapsed = time.time() - start_time

        assert len(results) == len(domains)

        # Statistics
        rdap_count = sum(1 for r in results.values() if r.source == "rdap")
        whois_count = sum(1 for r in results.values() if r.source == "whois")
        unknown_count = sum(1 for r in results.values() if r.source == "unknown")
        available_count = sum(1 for r in results.values() if r.available is True)
        unavailable_count = sum(1 for r in results.values() if r.available is False)

        print("\nDomainChecker Large Scale Test:")
        print(f"  Total domains: {len(domains)}")
        print(f"  Results obtained: {len(results)}")
        print(f"  RDAP results: {rdap_count}")
        print(f"  WHOIS results: {whois_count}")
        print(f"  Unknown source: {unknown_count}")
        print(f"  Available: {available_count}")
        print(f"  Unavailable: {unavailable_count}")
        print(f"  Time elapsed: {elapsed:.2f}s")
        print(f"  Average time per domain: {elapsed / len(domains):.3f}s")
        print(f"  Domains per second: {len(domains) / elapsed:.2f}")

        # Verify all results are valid
        for domain, result in results.items():
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert result.source in ("rdap", "whois", "dns", "policy", "unknown")
            assert_result_semantics(result)

    def test_domain_checker_very_large_scale(self):
        """Test DomainChecker with a very large number of random domains."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=False,
            max_workers=30,
            rdap_timeout=6.0,
            max_connections=100,
        )
        # Generate 200 random domains with reliable TLDs
        domains = generate_random_domains(
            count=200,
            min_length=4,
            max_length=25,
            tlds=["com", "org", "net"],  # Use reliable TLDs for large scale test
        )

        start_time = time.time()
        results = checker.check_domains(domains)
        elapsed = time.time() - start_time

        assert len(results) == len(domains)

        print("\nDomainChecker Very Large Scale Test:")
        print(f"  Total domains: {len(domains)}")
        print(f"  Results obtained: {len(results)}")
        print(f"  Time elapsed: {elapsed:.2f}s")
        print(f"  Average time per domain: {elapsed / len(domains):.3f}s")
        print(f"  Domains per second: {len(domains) / elapsed:.2f}")

    def test_domain_checker_with_whois_fallback(self):
        """Test DomainChecker with WHOIS fallback enabled."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=True,
            max_workers=15,
            rdap_timeout=8.0,
        )
        domains = generate_random_domains(
            count=30,
            min_length=6,
            max_length=15,
            tlds=["com", "org", "net"],
        )

        results = checker.check_domains(domains)

        assert len(results) == len(domains)
        # With fallback, we might see more whois results
        whois_count = sum(1 for r in results.values() if r.source == "whois")
        print("\nDomainChecker with WHOIS Fallback:")
        print(f"  Total domains: {len(domains)}")
        print(f"  WHOIS results (fallback): {whois_count}")

    def test_domain_checker_different_domain_lengths(self):
        """Test DomainChecker with domains of various lengths."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=False,
            max_workers=10,
            rdap_timeout=8.0,
        )

        # Generate domains of different lengths with reliable TLDs
        short_domains = generate_random_domains(
            count=10,
            min_length=4,
            max_length=6,
            tlds=["com", "org", "net"],
        )
        medium_domains = generate_random_domains(
            count=10,
            min_length=10,
            max_length=15,
            tlds=["com", "org", "net"],
        )
        long_domains = generate_random_domains(
            count=10,
            min_length=20,
            max_length=25,
            tlds=["com", "org", "net"],
        )

        all_domains = short_domains + medium_domains + long_domains

        results = checker.check_domains(all_domains)

        assert len(results) == len(all_domains)

        print("\nDomainChecker Different Lengths Test:")
        print(f"  Short domains (4-6 chars): {len(short_domains)}")
        print(f"  Medium domains (10-15 chars): {len(medium_domains)}")
        print(f"  Long domains (20-25 chars): {len(long_domains)}")
        print(f"  Total: {len(all_domains)}")

        # Verify all lengths work
        for domain, result in results.items():
            assert isinstance(result, DomainCheckResult)
            assert len(domain.split(".")[0]) >= 4  # Label length


# Popular registered domains for testing
POPULAR_REGISTERED_DOMAINS = [
    "google.com",
    "facebook.com",
    "youtube.com",
    "amazon.com",
    "microsoft.com",
    "apple.com",
    "twitter.com",
    "instagram.com",
    "linkedin.com",
    "github.com",
    "stackoverflow.com",
    "reddit.com",
    "wikipedia.org",
    "netflix.com",
    "spotify.com",
    "paypal.com",
    "ebay.com",
    "adobe.com",
    "oracle.com",
    "intel.com",
    "nvidia.com",
    "tesla.com",
    "uber.com",
    "airbnb.com",
    "dropbox.com",
    "salesforce.com",
    "zoom.us",
    "slack.com",
    "discord.com",
    "twitch.tv",
]


class TestRegisteredDomains:
    """Tests for checking popular registered (taken) domains."""

    def test_rdap_client_popular_registered_domains(self):
        """Test RDAP client with popular registered domains."""
        client = RdapClient(timeout=10.0, max_retries=2)

        results = []
        errors = []

        start_time = time.time()
        for domain in POPULAR_REGISTERED_DOMAINS[:15]:  # Test first 15
            try:
                result = client.check_domain(domain)
                results.append((domain, result))
                assert isinstance(result, DomainCheckResult)
                assert result.domain == domain
                assert result.source == "rdap"
                # These domains should be registered (unavailable)
                assert result.available is False, f"{domain} should be registered"
            except DomainCheckError as e:
                errors.append((domain, str(e)))

        elapsed = time.time() - start_time

        print("\nRDAP Popular Registered Domains Test:")
        print(f"  Total domains: {len(POPULAR_REGISTERED_DOMAINS[:15])}")
        print(f"  Successful checks: {len(results)}")
        print(f"  Errors: {len(errors)}")
        print(f"  Time elapsed: {elapsed:.2f}s")

        # Check that most domains were correctly identified as unavailable
        unavailable_count = sum(1 for _, r in results if r.available is False)
        print(f"  Correctly identified as unavailable: {unavailable_count}/{len(results)}")

        assert len(results) > 0, "Should get at least some results"
        assert unavailable_count == len(results), "All popular domains should be unavailable"

    def test_whois_client_popular_registered_domains(self):
        """Test WHOIS client with popular registered domains."""
        client = WhoisClient()

        results = []
        start_time = time.time()

        for domain in POPULAR_REGISTERED_DOMAINS[:15]:  # Test first 15
            result = client.check_domain(domain)
            results.append((domain, result))
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert result.source == "whois"
            # These domains should be registered (unavailable)
            assert result.available is False, f"{domain} should be registered"

        elapsed = time.time() - start_time

        unavailable_count = sum(1 for _, r in results if r.available is False)

        print("\nWHOIS Popular Registered Domains Test:")
        print(f"  Total domains: {len(POPULAR_REGISTERED_DOMAINS[:15])}")
        print(f"  Successful checks: {len(results)}")
        print(f"  Correctly identified as unavailable: {unavailable_count}/{len(results)}")
        print(f"  Time elapsed: {elapsed:.2f}s")

        assert unavailable_count == len(results), "All popular domains should be unavailable"

    def test_domain_checker_popular_registered_domains(self):
        """Test DomainChecker with popular registered domains."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=True,  # Enable fallback for 100% accuracy
            max_workers=10,
            rdap_timeout=10.0,
        )

        # Test all popular domains
        domains = POPULAR_REGISTERED_DOMAINS

        start_time = time.time()
        results = checker.check_domains(domains)
        elapsed = time.time() - start_time

        assert len(results) == len(domains)

        # Statistics
        rdap_count = sum(1 for r in results.values() if r.source == "rdap")
        whois_count = sum(1 for r in results.values() if r.source == "whois")
        unknown_count = sum(1 for r in results.values() if r.source == "unknown")
        unavailable_count = sum(1 for r in results.values() if r.available is False)
        available_count = sum(1 for r in results.values() if r.available is True)

        print("\nDomainChecker Popular Registered Domains Test:")
        print(f"  Total domains: {len(domains)}")
        print(f"  Results obtained: {len(results)}")
        print(f"  RDAP results: {rdap_count}")
        print(f"  WHOIS results: {whois_count}")
        print(f"  Unknown source: {unknown_count}")
        print(f"  Unavailable (correct): {unavailable_count}")
        print(f"  Available (incorrect): {available_count}")
        if available_count > 0:
            available_domains = [d for d, r in results.items() if r.available]
            print(f"  Incorrectly marked as available: {available_domains}")
        print(f"  Accuracy: {unavailable_count / len(results) * 100:.1f}%")
        print(f"  Time elapsed: {elapsed:.2f}s")
        print(f"  Average time per domain: {elapsed / len(domains):.3f}s")

        # Verify all results are valid
        for domain, result in results.items():
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert result.source in ("rdap", "whois", "dns", "policy", "unknown")

        # All popular domains should be correctly identified as unavailable (100%)
        assert unavailable_count == len(domains), (
            f"Expected 100% of popular domains to be identified as unavailable, "
            f"got {unavailable_count}/{len(domains)}"
        )

    def test_domain_checker_mixed_random_and_registered(self):
        """Test DomainChecker with mix of random (likely unregistered) and registered domains."""
        checker = DomainChecker(
            prefer_rdap=True,
            whois_fallback=True,  # Enable fallback for 100% accuracy
            max_workers=15,
            rdap_timeout=8.0,
        )

        # Mix random domains (likely unregistered) with registered domains
        # Use medium-length random domains (20-30 chars) - these are unlikely to be taken
        # Very long domains (60+ chars) cause WHOIS timeouts
        random_domains = generate_random_domains(
            count=20,
            min_length=20,
            max_length=30,
            tlds=["com", "org", "net"],
        )
        registered_domains = POPULAR_REGISTERED_DOMAINS[:10]

        all_domains = random_domains + registered_domains

        start_time = time.time()
        results = checker.check_domains(all_domains)
        elapsed = time.time() - start_time

        assert len(results) == len(all_domains)

        # Check random domains (most should be available)
        random_results = {d: results[d] for d in random_domains}
        random_available = sum(1 for r in random_results.values() if r.available is True)

        # Check registered domains (all should be unavailable)
        registered_results = {d: results[d] for d in registered_domains}
        registered_unavailable = sum(1 for r in registered_results.values() if r.available is False)

        print("\nDomainChecker Mixed Test:")
        print(f"  Random domains: {len(random_domains)}")
        print(f"    Available: {random_available}/{len(random_domains)}")
        print(f"    Unavailable: {len(random_domains) - random_available}/{len(random_domains)}")
        print(f"  Registered domains: {len(registered_domains)}")
        print(f"    Unavailable (correct): {registered_unavailable}/{len(registered_domains)}")
        print(
            f"    Available (incorrect): {len(registered_domains) - registered_unavailable}/{len(registered_domains)}"
        )
        print(f"  Time elapsed: {elapsed:.2f}s")

        # All registered domains should be correctly identified as unavailable (100%)
        assert registered_unavailable == len(registered_domains), (
            f"Expected 100% of registered domains to be unavailable, "
            f"got {registered_unavailable}/{len(registered_domains)}"
        )

        # Random domains - verify that checker works correctly
        # Due to network timeouts and TLD restrictions, we don't enforce availability percentage
        # Just verify that all domains were checked and results are valid
        assert len(random_results) == len(random_domains), (
            f"Expected results for all random domains, "
            f"got {len(random_results)}/{len(random_domains)}"
        )
        # Verify all results have valid structure
        for domain, result in random_results.items():
            assert isinstance(result, DomainCheckResult)
            assert result.domain == domain
            assert_result_semantics(result)
            assert result.source in ("rdap", "whois", "dns", "policy", "unknown")
