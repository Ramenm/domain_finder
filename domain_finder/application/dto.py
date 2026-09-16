"""Data Transfer Objects for use cases."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator, model_validator

TLD_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class DomainSearchRequest(BaseModel):
    """Validated request DTO for the domain-search use case."""

    topic: str = Field(..., min_length=1)
    iterations: int = Field(default=5, ge=1)
    per_request: int = Field(default=100, ge=1, le=300)
    llm_workers: int = Field(default=1, ge=1)
    tlds: list[str] = Field(default_factory=lambda: ["com"], min_length=1)
    provider: str = "openai"
    model: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    timeout: float = Field(default=60.0, gt=0.0)
    use_rdap: bool = True
    whois_fallback: bool = True
    max_workers: int = Field(default=20, ge=1)
    min_len: int = Field(default=4, ge=1, le=63)
    max_len: int = Field(default=15, ge=1, le=63)
    cooldown: float = Field(default=0.0, ge=0.0)
    cache_file: str = Field(default="domains_cache.sqlite3", min_length=1)
    clear_cache: bool = False
    results_txt: str = Field(default="results.txt", min_length=1)
    results_csv: str | None = "results.csv"
    skip_check: bool = False

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic must not be empty")
        return value

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value != "openai":
            raise ValueError("provider must be 'openai'")
        return value

    @field_validator("tlds")
    @classmethod
    def normalize_tlds(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            raw = value.strip().lower().strip(".")
            if not raw:
                continue
            try:
                ascii_tld = raw.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise ValueError(f"invalid TLD: {value!r}") from exc
            labels = ascii_tld.split(".")
            if any(not TLD_LABEL_RE.fullmatch(label) for label in labels):
                raise ValueError(f"invalid TLD: {value!r}")
            normalized.append(ascii_tld)
        if not normalized:
            raise ValueError("at least one non-empty TLD is required")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_length_range(self) -> DomainSearchRequest:
        if self.max_len < self.min_len:
            raise ValueError("max_len must be greater than or equal to min_len")
        return self


@dataclass(frozen=True)
class SearchProgress:
    """Phase-level progress event for user-facing search feedback."""

    phase: str
    iteration: int
    iterations: int
    count: int | None = None
    message: str | None = None


class DomainSearchResult(BaseModel):
    """Result DTO for domain search use case."""

    total_iterations: int
    iterations_attempted: int
    iterations_completed: int
    iterations_failed: int
    total_generated: int
    total_checked: int = 0
    total_skipped: int = 0
    total_available: int
    available_domains: list[str]
    total_unregistered: int = 0
    unregistered_domains: list[str] = Field(default_factory=list)
    total_registered: int = 0
    total_reserved: int = 0
    total_inconclusive: int = 0
    results_txt: str
    results_csv: str | None = None
