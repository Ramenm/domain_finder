"""Data Transfer Objects for use cases."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class DomainSearchRequest:
    """Request DTO for domain search use case."""

    topic: str
    iterations: int = 5
    per_request: int = 100
    llm_workers: int = 1
    tlds: list[str] = None  # type: ignore
    provider: str = "openai"
    model: str | None = None
    temperature: float = 0.7
    timeout: float = 60.0
    use_rdap: bool = True
    whois_fallback: bool = False
    max_workers: int = 20
    min_len: int = 4
    max_len: int = 15
    cooldown: float = 2.0
    cache_file: str = "domains_cache.json"
    clear_cache: bool = False
    results_txt: str = "results.txt"
    results_csv: str | None = "results.csv"
    skip_check: bool = False

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.tlds is None:
            self.tlds = ["com"]


class DomainSearchResult(BaseModel):
    """Result DTO for domain search use case."""

    total_iterations: int
    total_generated: int
    total_available: int
    available_domains: list[str]
    results_txt: str
    results_csv: str | None = None
