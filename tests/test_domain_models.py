"""Tests for domain models."""

import pytest

from domain_finder.domain.models import DomainCandidate, DomainCheckResult, ProviderConfig, DomainSearchParams


def test_domain_candidate_from_string():
    """Test creating DomainCandidate from string."""
    candidate = DomainCandidate.from_string("example.com")
    assert candidate.name == "example.com"
    assert candidate.label == "example"
    assert candidate.tld == "com"


def test_domain_candidate_validation():
    """Test domain candidate validation."""
    # Valid domain
    candidate = DomainCandidate(name="test.com", label="test", tld="com")
    assert candidate.name == "test.com"

    # Invalid: no dot
    with pytest.raises(ValueError):
        DomainCandidate.from_string("nodot")

    # Invalid: multiple dots
    with pytest.raises(ValueError):
        DomainCandidate.from_string("sub.example.com")


def test_domain_check_result():
    """Test DomainCheckResult creation."""
    result = DomainCheckResult(
        domain="example.com",
        available=True,
        source="rdap",
        checked_at=1234567890.0,
    )
    assert result.domain == "example.com"
    assert result.available is True
    assert result.source == "rdap"


def test_provider_config():
    """Test ProviderConfig validation."""
    config = ProviderConfig(
        provider="openai",
        model="gpt-4o",
        temperature=0.7,
        timeout=60.0,
    )
    assert config.provider == "openai"
    assert config.temperature == 0.7

    # Invalid provider
    with pytest.raises(ValueError):
        ProviderConfig(provider="invalid", model="test", temperature=0.7, timeout=60.0)


def test_domain_search_params():
    """Test DomainSearchParams validation."""
    params = DomainSearchParams(
        topic="AI tools",
        tlds=["com", "io"],
        count=100,
        language="en",
        min_len=4,
        max_len=15,
    )
    assert params.topic == "AI tools"
    assert params.tlds == ["com", "io"]
    assert params.count == 100

    # Invalid language
    with pytest.raises(ValueError):
        DomainSearchParams(
            topic="test",
            tlds=["com"],
            count=10,
            language="invalid",
        )

    # Invalid max_len < min_len
    with pytest.raises(ValueError):
        DomainSearchParams(
            topic="test",
            tlds=["com"],
            count=10,
            min_len=10,
            max_len=5,
        )

