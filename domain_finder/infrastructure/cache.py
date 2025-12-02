"""Domain availability cache implementation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from domain_finder.domain.models import CacheEntry, DomainCheckResult
from domain_finder.domain.ports import ResultRepositoryPort


class CacheManager(ResultRepositoryPort):
    """File-based cache manager for domain check results."""

    def __init__(self, cache_file: str = "domains_cache.json") -> None:
        """
        Initialize cache manager.

        Args:
            cache_file: Path to cache file
        """
        self.path = Path(cache_file)
        self.data: Dict[str, CacheEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from file."""
        if not self.path.exists():
            self.data = {}
            return

        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = {
                k: CacheEntry(**v) if isinstance(v, dict) and "available" in v else CacheEntry(
                    bool(v), "unknown", time.time()
                )
                for k, v in obj.items()
            }
        except Exception:  # noqa: BLE001
            self.data = {}

    def save(self) -> None:
        """Save cache to file."""
        self.path.write_text(
            json.dumps(
                {k: {"available": v.available, "source": v.source, "checked_at": v.checked_at} for k, v in self.data.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def get_cached_result(self, domain: str) -> Optional[DomainCheckResult]:
        """
        Get cached check result for a domain.

        Args:
            domain: Domain name to look up

        Returns:
            Cached result if exists, None otherwise
        """
        entry = self.data.get(domain)
        if entry:
            return DomainCheckResult(
                domain=domain,
                available=entry.available,
                source=entry.source,
                checked_at=entry.checked_at,
            )
        return None

    def cache_result(self, result: DomainCheckResult) -> None:
        """
        Cache a domain check result.

        Args:
            result: Domain check result to cache
        """
        self.data[result.domain] = CacheEntry(
            available=result.available,
            source=result.source,
            checked_at=result.checked_at,
        )

    def save_available_domains(self, domains: List[DomainCheckResult]) -> None:
        """
        Save available domains to persistent storage.

        Note: This implementation only caches results. Actual persistence
        is handled by ResultWriter in persistence.py.

        Args:
            domains: List of available domain check results
        """
        for result in domains:
            if result.available:
                self.cache_result(result)
        self.save()

    def clear(self) -> None:
        """Clear all cached data."""
        self.data = {}
        self.save()

    def known(self) -> Dict[str, CacheEntry]:
        """Get all known cache entries."""
        return self.data.copy()

