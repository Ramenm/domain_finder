"""Domain models using Pydantic."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator


class DomainCandidate(BaseModel):
    """Represents a candidate domain name."""

    name: str = Field(..., description="Domain name (e.g., 'example.com')")
    tld: str = Field(..., description="Top-level domain (e.g., 'com')")
    label: str = Field(..., description="Second-level label (e.g., 'example')")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate domain name format."""
        v = v.strip().lower()
        if "." not in v:
            raise ValueError("Domain name must contain a dot")
        if v.count(".") != 1:
            raise ValueError("Domain name must have exactly one dot (no subdomains)")
        return v

    @classmethod
    def from_string(cls, domain_str: str) -> DomainCandidate:
        """Create DomainCandidate from string like 'example.com'."""
        domain_str = domain_str.strip().lower()
        if "." not in domain_str:
            raise ValueError(f"Invalid domain format: {domain_str}")
        parts = domain_str.split(".", 1)
        return cls(name=domain_str, label=parts[0], tld=parts[1])


class DomainCheckResult(BaseModel):
    """Result of domain availability check."""

    domain: str = Field(..., description="Domain name that was checked")
    available: bool = Field(..., description="Whether the domain is available")
    source: str = Field(..., description="Source of check: 'rdap' or 'whois'")
    checked_at: float = Field(..., description="Unix timestamp of check")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Validate source value."""
        if v not in ("rdap", "whois", "unknown"):
            raise ValueError("Source must be 'rdap', 'whois', or 'unknown'")
        return v


class ProviderConfig(BaseModel):
    """Configuration for LLM provider."""

    provider: str = Field(..., description="Provider name: 'openai'")
    model: str = Field(..., description="Model identifier")
    temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Temperature for generation"
    )
    timeout: float = Field(default=60.0, gt=0.0, description="Request timeout in seconds")
    api_key: str | None = Field(default=None, description="API key for the provider")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate provider name."""
        v = v.lower().strip()
        if v not in ("openai",):
            raise ValueError("Provider must be 'openai'")
        return v


class DomainSearchParams(BaseModel):
    """Parameters for domain search/generation."""

    topic: str = Field(..., description="Topic/theme for domain generation")
    tlds: list[str] = Field(..., min_length=1, description="List of allowed TLDs")
    count: int = Field(..., ge=1, le=300, description="Number of domains to generate")
    min_len: int = Field(default=4, ge=1, le=63, description="Minimum label length")
    max_len: int = Field(default=15, ge=1, le=63, description="Maximum label length")

    @field_validator("max_len")
    @classmethod
    def validate_max_len(cls, v: int, info) -> int:
        """Ensure max_len >= min_len."""
        if "min_len" in info.data and v < info.data["min_len"]:
            raise ValueError("max_len must be >= min_len")
        return v


@dataclass(frozen=True)
class CacheEntry:
    """Entry in domain availability cache."""

    available: bool
    source: str
    checked_at: float
