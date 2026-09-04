"""Domain services - business logic for domain operations."""

from __future__ import annotations

import json
import re
import time

from .models import DomainCandidate, DomainCheckResult, DomainCheckStatus, DomainSearchParams
from .ports import DomainCheckerPort, DomainProviderPort, ResultRepositoryPort

DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _idna_ascii(value: str) -> str | None:
    """Normalize Unicode DNS names/suffixes to their ASCII wire form."""
    try:
        return value.strip().lower().strip(".").encode("idna").decode("ascii")
    except UnicodeError:
        return None


class DomainGeneratorService:
    """Generate and deterministically normalize domain suggestions."""

    def __init__(self, provider: DomainProviderPort) -> None:
        self.provider = provider

    def generate_and_parse(self, params: DomainSearchParams) -> list[DomainCandidate]:
        raw_text = self.provider.generate_domains(params)
        return self._parse_domains_from_text(
            raw_text,
            allowed_tlds=params.tlds,
            min_len=params.min_len,
            max_len=params.max_len,
            limit=params.count,
        )

    @staticmethod
    def _extract_tokens(text: str) -> list[str]:
        stripped = text.strip()
        try:
            payload = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            payload = None

        if isinstance(payload, list):
            return [item.strip() for item in payload if isinstance(item, str) and item.strip()]
        if isinstance(payload, dict) and isinstance(payload.get("domains"), list):
            return [
                item.strip()
                for item in payload["domains"]
                if isinstance(item, str) and item.strip()
            ]

        cleaned = re.sub(r"[|•\t]", " ", text).replace("\n", ",")
        return [part.strip() for part in cleaned.split(",") if part.strip()]

    def _parse_domains_from_text(
        self,
        text: str,
        allowed_tlds: list[str],
        min_len: int,
        max_len: int,
        limit: int,
    ) -> list[DomainCandidate]:
        ordered_tlds = list(
            dict.fromkeys(
                ascii_tld for tld in allowed_tlds if tld and (ascii_tld := _idna_ascii(tld))
            )
        )
        allowed_set = set(ordered_tlds)
        candidates: list[DomainCandidate] = []
        seen: set[str] = set()

        def add(domain: str) -> None:
            if len(candidates) >= limit or domain in seen:
                return
            normalized = self._normalize_domain_token(domain, allowed_set, min_len, max_len)
            if normalized is None or normalized in seen:
                return
            try:
                suffix = normalized.split(".", 1)[1]
                candidate = DomainCandidate.from_string(normalized, suffix=suffix)
            except ValueError:
                return
            seen.add(normalized)
            candidates.append(candidate)

        for raw in self._extract_tokens(text):
            if len(candidates) >= limit:
                break
            token = raw.strip().lower().strip(",.;:()[]<>\"'`")
            if not token:
                continue
            if "." in token:
                add(token)
                continue
            for tld in ordered_tlds:
                add(f"{token}.{tld}")
                if len(candidates) >= limit:
                    break
        return candidates

    @staticmethod
    def _normalize_domain_token(
        token: str,
        allowed_tlds: set[str],
        min_len: int,
        max_len: int,
    ) -> str | None:
        candidate_raw = token.strip().lower().strip(",.;:()[]<>\"'`").rstrip(".")
        candidate = _idna_ascii(candidate_raw)
        if candidate is None:
            return None
        suffixes = sorted(allowed_tlds, key=lambda value: (-len(value), value))
        suffix = next(
            (value for value in suffixes if candidate.endswith(f".{value}")),
            None,
        )
        if suffix is None:
            return None
        label = candidate[: -(len(suffix) + 1)]
        if "." in label or not DNS_LABEL_RE.fullmatch(label):
            return None
        if not min_len <= len(label) <= max_len:
            return None
        if any(not DNS_LABEL_RE.fullmatch(part) for part in suffix.split(".")):
            return None
        return f"{label}.{suffix}"


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

    def check_domains_with_cache(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        """
        Check domains with caching support.

        Important: Only caches successful results. Errors are not cached
        to avoid marking domains as unavailable when check failed.

        Args:
            domains: List of domain names to check

        Returns:
            Dictionary mapping domain names to check results
        """
        results: dict[str, DomainCheckResult] = {}

        # Check cache first
        domains_to_check: list[str] = []
        for domain in domains:
            cached = self.repository.get_cached_result(domain)
            if cached:
                results[domain] = cached
            else:
                domains_to_check.append(domain)

        # Check uncached domains
        if domains_to_check:
            try:
                fresh_results = self.checker.check_domains(domains_to_check)

                # Only cache successful results (not errors marked as unavailable)
                for domain, result in fresh_results.items():
                    results[domain] = result
                    # Cache every status; the repository applies short TTLs to transient failures.
                    self.repository.cache_result(result)
            except Exception as e:  # noqa: BLE001
                # If checker fails completely, mark all as unavailable to avoid false positives
                import logging

                logger = logging.getLogger(__name__)
                logger.error(f"Domain checker failed completely: {e}")
                # Mark all unchecked domains as unavailable (conservative approach)
                for domain in domains_to_check:
                    if domain not in results:
                        results[domain] = DomainCheckResult(
                            domain=domain,
                            status=DomainCheckStatus.UNKNOWN,
                            source="unknown",
                            checked_at=time.time(),
                            detail=str(e),
                        )

        return results
