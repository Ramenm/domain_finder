"""Domain services - business logic for domain operations."""

from __future__ import annotations

import re
from typing import List, Optional

from .errors import ValidationError
from .models import DomainCandidate, DomainSearchParams
from .ports import DomainCheckerPort, DomainProviderPort, ResultRepositoryPort

DOMAIN_RE = re.compile(
    r"\b(?P<label>[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)\.(?P<tld>[a-zA-Z]{2,24})\b"
)


class DomainGeneratorService:
    """Service for generating and parsing domain suggestions."""

    def __init__(self, provider: DomainProviderPort) -> None:
        """
        Initialize domain generator service.

        Args:
            provider: LLM provider port for generating suggestions
        """
        self.provider = provider

    def generate_and_parse(
        self, params: DomainSearchParams
    ) -> List[DomainCandidate]:
        """
        Generate domain suggestions and parse them into DomainCandidate objects.

        Args:
            params: Parameters for domain generation

        Returns:
            List of parsed domain candidates

        Raises:
            ValidationError: If parsing fails
        """
        # Generate raw text from LLM
        raw_text = self.provider.generate_domains(params)

        # Parse domains from text
        candidates = self._parse_domains_from_text(
            raw_text,
            allowed_tlds=params.tlds,
            min_len=params.min_len,
            max_len=params.max_len,
            limit=params.count,
        )

        return candidates

    def _parse_domains_from_text(
        self,
        text: str,
        allowed_tlds: List[str],
        min_len: int,
        max_len: int,
        limit: int,
    ) -> List[DomainCandidate]:
        """
        Parse domain candidates from LLM response text.

        Args:
            text: Raw text from LLM
            allowed_tlds: List of allowed TLDs
            min_len: Minimum label length
            max_len: Maximum label length
            limit: Maximum number of domains to extract

        Returns:
            List of valid domain candidates
        """
        # Clean text
        cleaned = re.sub(r"[|•\t]", " ", text)
        cleaned = cleaned.replace("\n", ",")

        # Split by commas
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]

        candidates: List[DomainCandidate] = []
        seen: set[str] = set()
        allowed_tlds_set = {t.lstrip(".").lower() for t in allowed_tlds}
        force_tld = allowed_tlds[0] if len(allowed_tlds) == 1 else None

        for part in parts:
            if len(candidates) >= limit:
                break

            # Try to extract domain
            domain_str = self._normalize_domain_token(
                part, allowed_tlds_set, force_tld, min_len, max_len
            )

            if domain_str and domain_str not in seen:
                try:
                    candidate = DomainCandidate.from_string(domain_str)
                    candidates.append(candidate)
                    seen.add(domain_str)
                except ValueError:
                    continue

        return candidates

    def _normalize_domain_token(
        self,
        token: str,
        allowed_tlds: set[str],
        force_tld: Optional[str],
        min_len: int,
        max_len: int,
    ) -> Optional[str]:
        """
        Normalize a token to a valid domain string.

        Args:
            token: Input token
            allowed_tlds: Set of allowed TLDs
            force_tld: TLD to use if token has no TLD
            min_len: Minimum label length
            max_len: Maximum label length

        Returns:
            Normalized domain string or None if invalid
        """
        token = token.strip().lower()
        token = token.strip(",.;:()[]<>\"'`")

        # Add TLD if missing
        if "." not in token:
            use_tld = (force_tld or (list(allowed_tlds)[0] if allowed_tlds else "com")).lstrip(".")
            candidate = f"{token}.{use_tld}"
        else:
            candidate = token

        # Validate format
        match = DOMAIN_RE.fullmatch(candidate)
        if not match:
            return None

        label = match.group("label")
        tld = match.group("tld")

        # Check length
        if len(label) < min_len or len(label) > max_len:
            return None

        # Check TLD
        if allowed_tlds and tld not in allowed_tlds:
            if force_tld:
                return f"{label}.{force_tld.lstrip('.')}"
            return None

        # Ensure exactly one dot
        if candidate.count(".") != 1:
            return None

        # No leading/trailing hyphens
        if label.startswith("-") or label.endswith("-"):
            return None

        return f"{label}.{tld}"


class DomainCheckService:
    """Service for checking domain availability with caching."""

    def __init__(
        self,
        checker: DomainCheckerPort,
        repository: ResultRepositoryPort,
    ) -> None:
        """
        Initialize domain check service.

        Args:
            checker: Domain checker port
            repository: Result repository port for caching
        """
        self.checker = checker
        self.repository = repository

    def check_domains_with_cache(
        self, domains: List[str]
    ) -> dict[str, DomainCheckResult]:
        """
        Check domains with caching support.

        Args:
            domains: List of domain names to check

        Returns:
            Dictionary mapping domain names to check results
        """
        results: dict[str, DomainCheckResult] = {}

        # Check cache first
        domains_to_check: List[str] = []
        for domain in domains:
            cached = self.repository.get_cached_result(domain)
            if cached:
                results[domain] = cached
            else:
                domains_to_check.append(domain)

        # Check uncached domains
        if domains_to_check:
            fresh_results = self.checker.check_domains(domains_to_check)
            results.update(fresh_results)

            # Cache new results
            for result in fresh_results.values():
                self.repository.cache_result(result)

        return results

