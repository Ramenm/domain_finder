"""SQLite-backed cache for domain check results."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from domain_finder.domain.models import CacheEntry, DomainCheckResult, DomainCheckStatus
from domain_finder.domain.ports import ResultRepositoryPort


class CacheManager(ResultRepositoryPort):
    """Thread-safe SQLite cache with status-aware TTLs and legacy JSON import."""

    def __init__(
        self,
        cache_file: str = "domains_cache.sqlite3",
        available_ttl: float = 5 * 60,
        registered_ttl: float = 60 * 60,
        error_ttl: float = 30,
        clock: Callable[[], float] = time.time,
    ) -> None:
        requested = Path(cache_file)
        self.legacy_json_path = requested if requested.suffix.lower() == ".json" else None
        self.path = requested.with_suffix(".sqlite3") if self.legacy_json_path else requested
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.available_ttl = available_ttl
        self.registered_ttl = registered_ttl
        self.error_ttl = error_ttl
        self._clock = clock
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self.hits = 0
        self.misses = 0
        self.stale_evictions = 0
        self._initialize()
        self._import_legacy_once()

    def _initialize(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_cache (
                    domain TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    checked_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    detail TEXT,
                    latency_ms REAL,
                    retries INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain_cache_expires ON domain_cache(expires_at)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS cache_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.commit()

    def _ttl_for(self, status: DomainCheckStatus) -> float:
        if status in {
            DomainCheckStatus.AVAILABLE,
            DomainCheckStatus.REGISTRABLE,
            DomainCheckStatus.UNREGISTERED,
        }:
            return self.available_ttl
        if status in {DomainCheckStatus.REGISTERED, DomainCheckStatus.RESERVED}:
            return self.registered_ttl
        return self.error_ttl

    def _mark_legacy_imported(self) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache_metadata(key, value) VALUES('legacy_imported', '1')"
        )
        self._conn.commit()

    def _import_legacy_once(self) -> None:
        if self.legacy_json_path is None:
            return
        with self._lock:
            marker = self._conn.execute(
                "SELECT value FROM cache_metadata WHERE key='legacy_imported'"
            ).fetchone()
            if marker is not None:
                return
            try:
                payload = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for domain, raw in payload.items():
                        if isinstance(raw, dict) and "available" in raw:
                            available = bool(raw["available"])
                            source = str(raw.get("source", "unknown"))
                            checked_at = float(raw.get("checked_at", self._clock()))
                        elif isinstance(raw, bool):
                            available = raw
                            source = "unknown"
                            checked_at = self._clock()
                        else:
                            continue
                        status = (
                            DomainCheckStatus.AVAILABLE
                            if available
                            else DomainCheckStatus.REGISTERED
                        )
                        self.cache_result(
                            DomainCheckResult(
                                domain=str(domain),
                                status=status,
                                source=source
                                if source in {"rdap", "whois", "dns", "cache", "policy", "unknown"}
                                else "unknown",
                                checked_at=checked_at,
                            )
                        )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            self._mark_legacy_imported()

    def save(self) -> None:
        """Flush pending SQLite work for compatibility with the old API."""
        with self._lock:
            self._conn.commit()

    def get_cached_result(self, domain: str) -> DomainCheckResult | None:
        now = self._clock()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM domain_cache WHERE domain = ?", (domain,)
            ).fetchone()
            if row is None:
                self.misses += 1
                return None
            if float(row["expires_at"]) <= now:
                self._conn.execute("DELETE FROM domain_cache WHERE domain = ?", (domain,))
                self._conn.commit()
                self.stale_evictions += 1
                self.misses += 1
                return None
            try:
                status = DomainCheckStatus(str(row["status"]))
            except ValueError:
                self._conn.execute("DELETE FROM domain_cache WHERE domain = ?", (domain,))
                self._conn.commit()
                self.misses += 1
                return None
            self.hits += 1
            return DomainCheckResult(
                domain=domain,
                status=status,
                source=str(row["source"]),
                checked_at=float(row["checked_at"]),
                detail=row["detail"],
                latency_ms=row["latency_ms"],
                retries=int(row["retries"]),
            )

    def cache_result(self, result: DomainCheckResult) -> None:
        status = result.status or DomainCheckStatus.UNKNOWN
        expires_at = result.checked_at + self._ttl_for(status)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO domain_cache(
                    domain, status, source, checked_at, expires_at, detail, latency_ms, retries
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    status=excluded.status, source=excluded.source,
                    checked_at=excluded.checked_at, expires_at=excluded.expires_at,
                    detail=excluded.detail, latency_ms=excluded.latency_ms, retries=excluded.retries
                """,
                (
                    result.domain,
                    status.value,
                    result.source,
                    result.checked_at,
                    expires_at,
                    result.detail,
                    result.latency_ms,
                    result.retries,
                ),
            )
            self._conn.commit()

    def save_available_domains(self, domains: list[DomainCheckResult]) -> None:
        for item in domains:
            if item.is_registrable:
                self.cache_result(item)

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM domain_cache")
            self._conn.commit()

    def known(self) -> dict[str, CacheEntry]:
        now = self._clock()
        with self._lock:
            self._conn.execute("DELETE FROM domain_cache WHERE expires_at <= ?", (now,))
            rows = self._conn.execute(
                """
                SELECT domain, status, source, checked_at
                FROM domain_cache
                WHERE status IN (?, ?, ?, ?, ?)
                """,
                (
                    DomainCheckStatus.AVAILABLE.value,
                    DomainCheckStatus.REGISTRABLE.value,
                    DomainCheckStatus.UNREGISTERED.value,
                    DomainCheckStatus.RESERVED.value,
                    DomainCheckStatus.REGISTERED.value,
                ),
            ).fetchall()
            self._conn.commit()

        def legacy_available(status_value: str) -> bool | None:
            if status_value in {
                DomainCheckStatus.AVAILABLE.value,
                DomainCheckStatus.REGISTRABLE.value,
            }:
                return True
            if status_value in {
                DomainCheckStatus.REGISTERED.value,
                DomainCheckStatus.RESERVED.value,
            }:
                return False
            return None

        return {
            str(row["domain"]): CacheEntry(
                available=legacy_available(str(row["status"])),
                source=str(row["source"]),
                checked_at=float(row["checked_at"]),
            )
            for row in rows
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
