from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.infrastructure.cache import CacheManager


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def result(
    domain: str, status: DomainCheckStatus, checked_at: float | None = None
) -> DomainCheckResult:
    return DomainCheckResult(
        domain=domain,
        status=status,
        source="rdap",
        checked_at=time.time() if checked_at is None else checked_at,
    )


def test_sqlite_cache_uses_wal_and_round_trips(tmp_path: Path) -> None:
    cache = CacheManager(str(tmp_path / "cache.sqlite3"))
    cache.cache_result(result("example.com", DomainCheckStatus.REGISTERED))
    loaded = cache.get_cached_result("example.com")
    assert loaded is not None
    assert loaded.status is DomainCheckStatus.REGISTERED

    with sqlite3.connect(cache.path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_ttl_depends_on_status_and_stale_entries_are_evicted(tmp_path: Path) -> None:
    clock = Clock()
    cache = CacheManager(
        str(tmp_path / "cache.sqlite3"),
        available_ttl=5,
        registered_ttl=60,
        error_ttl=2,
        clock=clock,
    )
    cache.cache_result(result("free.com", DomainCheckStatus.AVAILABLE, clock()))
    cache.cache_result(result("taken.com", DomainCheckStatus.REGISTERED, clock()))
    cache.cache_result(result("slow.com", DomainCheckStatus.NETWORK_ERROR, clock()))

    clock.value += 3
    assert cache.get_cached_result("slow.com") is None
    assert cache.get_cached_result("free.com") is not None
    assert cache.get_cached_result("taken.com") is not None

    clock.value += 3
    assert cache.get_cached_result("free.com") is None
    assert cache.get_cached_result("taken.com") is not None


def test_upsert_replaces_old_result(tmp_path: Path) -> None:
    cache = CacheManager(str(tmp_path / "cache.sqlite3"))
    now = time.time()
    cache.cache_result(result("name.com", DomainCheckStatus.AVAILABLE, now))
    cache.cache_result(result("name.com", DomainCheckStatus.REGISTERED, now + 1))
    loaded = cache.get_cached_result("name.com")
    assert loaded is not None
    assert loaded.status is DomainCheckStatus.REGISTERED
    assert loaded.checked_at == now + 1


def test_legacy_json_is_imported_into_sqlite_once(tmp_path: Path) -> None:
    legacy = tmp_path / "domains_cache.json"
    legacy.write_text(
        json.dumps(
            {
                "free.com": {"available": True, "source": "rdap", "checked_at": 1000.0},
                "taken.com": {"available": False, "source": "rdap", "checked_at": 1000.0},
            }
        ),
        encoding="utf-8",
    )
    clock = Clock(1001.0)
    cache = CacheManager(str(legacy), available_ttl=100, registered_ttl=100, clock=clock)

    assert cache.path.suffix == ".sqlite3"
    assert cache.get_cached_result("free.com").status is DomainCheckStatus.AVAILABLE  # type: ignore[union-attr]
    assert cache.get_cached_result("taken.com").status is DomainCheckStatus.REGISTERED  # type: ignore[union-attr]
    assert legacy.exists()

    legacy.write_text(json.dumps({"new.com": True}), encoding="utf-8")
    reopened = CacheManager(str(legacy), available_ttl=100, registered_ttl=100, clock=clock)
    assert reopened.get_cached_result("new.com") is None


def test_corrupt_legacy_json_does_not_break_cache(tmp_path: Path) -> None:
    legacy = tmp_path / "domains_cache.json"
    legacy.write_text("{broken", encoding="utf-8")
    cache = CacheManager(str(legacy))
    assert cache.get_cached_result("anything.com") is None


def test_concurrent_reads_are_safe(tmp_path: Path) -> None:
    cache = CacheManager(str(tmp_path / "cache.sqlite3"))
    cache.cache_result(result("example.com", DomainCheckStatus.REGISTERED))

    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: cache.get_cached_result("example.com"), range(50)))

    assert all(value is not None for value in values)
    assert all(value.status is DomainCheckStatus.REGISTERED for value in values if value)


def test_known_excludes_expired_entries(tmp_path: Path) -> None:
    clock = Clock()
    cache = CacheManager(str(tmp_path / "cache.sqlite3"), available_ttl=1, clock=clock)
    cache.cache_result(result("soon-stale.com", DomainCheckStatus.AVAILABLE, clock()))
    assert "soon-stale.com" in cache.known()
    clock.value += 2
    assert "soon-stale.com" not in cache.known()


def test_search_request_defaults_to_sqlite_cache() -> None:
    from domain_finder.application.dto import DomainSearchRequest

    request = DomainSearchRequest(topic="test")
    assert request.cache_file.endswith(".sqlite3")
