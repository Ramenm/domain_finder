"""Domain models using Pydantic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class DomainCandidate(BaseModel):
    """Represents a candidate domain name."""

    name: str = Field(..., description="Domain name (e.g., 'example.com')")
    tld: str = Field(..., description="Top-level domain (e.g., 'com')")
    label: str = Field(..., description="Second-level label (e.g., 'example')")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Normalize a registrable domain, including multi-label suffixes."""
        v = v.strip().lower().rstrip(".")
        if "." not in v or v.startswith(".") or ".." in v:
            raise ValueError("Domain name must contain a registrable label and suffix")
        return v

    @model_validator(mode="after")
    def validate_parts(self) -> DomainCandidate:
        """Keep name, registrable label, and configured suffix consistent."""
        if "." in self.label or not self.label:
            raise ValueError("Domain label must be a single non-empty DNS label")
        if not self.tld or self.name != f"{self.label}.{self.tld}":
            raise ValueError("Domain parts do not match domain name")
        return self

    @classmethod
    def from_string(cls, domain_str: str, suffix: str | None = None) -> DomainCandidate:
        """Create a candidate, requiring explicit context for multi-label suffixes."""
        domain_str = domain_str.strip().lower().rstrip(".")
        if suffix is None:
            if domain_str.count(".") != 1:
                raise ValueError(f"Ambiguous domain format without suffix context: {domain_str}")
            label, suffix = domain_str.split(".", 1)
        else:
            suffix = suffix.strip().lower().lstrip(".").rstrip(".")
            ending = f".{suffix}"
            if not suffix or not domain_str.endswith(ending):
                raise ValueError(f"Domain does not match suffix {suffix!r}: {domain_str}")
            label = domain_str[: -len(ending)]
            if not label or "." in label:
                raise ValueError(
                    f"Domain contains a subdomain before suffix {suffix!r}: {domain_str}"
                )
        return cls(name=domain_str, label=label, tld=suffix)


class DomainCheckStatus(str, Enum):
    """Outcome of a domain availability lookup."""

    AVAILABLE = "available"  # legacy positive signal; prefer REGISTRABLE
    REGISTRABLE = "registrable"
    UNREGISTERED = "unregistered"
    RESERVED = "reserved"
    REGISTERED = "registered"
    UNKNOWN = "unknown"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class DomainCheckResult(BaseModel):
    """Result of a domain registry-state check with explicit uncertainty."""

    domain: str = Field(..., description="Domain name that was checked")
    status: DomainCheckStatus | None = None
    available: bool | None = Field(
        default=None, description="True/False only for definitive outcomes"
    )
    source: str = Field(..., description="Source of check")
    checked_at: float = Field(..., description="Unix timestamp of check")
    detail: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    retries: int = Field(default=0, ge=0)

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Validate source value."""
        if v not in ("rdap", "whois", "dns", "cache", "policy", "unknown"):
            raise ValueError("Unsupported domain check source")
        return v

    @model_validator(mode="after")
    def normalize_status(self) -> DomainCheckResult:
        """Infer legacy boolean results and keep uncertainty explicit."""
        if self.status is None:
            if self.source == "unknown":
                self.status = DomainCheckStatus.UNKNOWN
            elif self.available is True:
                self.status = DomainCheckStatus.AVAILABLE
            elif self.available is False:
                self.status = DomainCheckStatus.REGISTERED
            else:
                self.status = DomainCheckStatus.UNKNOWN

        if self.status in (DomainCheckStatus.AVAILABLE, DomainCheckStatus.REGISTRABLE):
            self.available = True
        elif self.status in (DomainCheckStatus.REGISTERED, DomainCheckStatus.RESERVED):
            self.available = False
        else:
            self.available = None
        return self

    @property
    def is_definitive(self) -> bool:
        """Return whether the registry/policy state is known definitively."""
        return self.status in (
            DomainCheckStatus.AVAILABLE,
            DomainCheckStatus.REGISTRABLE,
            DomainCheckStatus.UNREGISTERED,
            DomainCheckStatus.RESERVED,
            DomainCheckStatus.REGISTERED,
        )

    @property
    def is_registrable(self) -> bool:
        """Return True only for an explicit positive registration signal."""
        return self.status in (DomainCheckStatus.AVAILABLE, DomainCheckStatus.REGISTRABLE)

    @property
    def is_unregistered(self) -> bool:
        """Return whether no registered domain object exists."""
        return self.status in (
            DomainCheckStatus.AVAILABLE,
            DomainCheckStatus.REGISTRABLE,
            DomainCheckStatus.UNREGISTERED,
        )


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
    strategy: str | None = Field(default=None, description="Generation strategy hint")

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

    available: bool | None
    source: str
    checked_at: float
