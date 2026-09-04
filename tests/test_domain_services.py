"""Tests for domain services."""

from domain_finder.domain.models import DomainCandidate, DomainSearchParams
from domain_finder.domain.ports import DomainProviderPort
from domain_finder.domain.services import DomainGeneratorService


class MockProvider(DomainProviderPort):
    """Mock LLM provider for testing."""

    def generate_domains(self, params: DomainSearchParams) -> str:
        """Return mock domain suggestions."""
        return "example.com, test.io, demo.ai, sample.org"


def test_domain_generator_service():
    """Test domain generation and parsing."""
    provider = MockProvider()
    service = DomainGeneratorService(provider)

    params = DomainSearchParams(
        topic="test",
        tlds=["com", "io", "ai"],
        count=10,
        min_len=4,
        max_len=15,
    )

    candidates = service.generate_and_parse(params)
    assert len(candidates) > 0
    assert all(isinstance(c, DomainCandidate) for c in candidates)
    assert all(c.name.count(".") == 1 for c in candidates)


def test_domain_generator_service_parsing():
    """Test domain parsing from text."""
    provider = MockProvider()
    service = DomainGeneratorService(provider)

    text = "example.com, test.io, invalid-domain, another.com"
    candidates = service._parse_domains_from_text(
        text,
        allowed_tlds=["com", "io"],
        min_len=4,
        max_len=15,
        limit=10,
    )

    # Bare labels are valid generation output and expand over allowed TLDs in order.
    assert [c.name for c in candidates] == [
        "example.com",
        "test.io",
        "invalid-domain.com",
        "invalid-domain.io",
        "another.com",
    ]
    assert all(c.tld in ["com", "io"] for c in candidates)
