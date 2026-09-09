from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from domain_finder.domain.models import DomainCheckStatus


@dataclass(frozen=True)
class RegistryProfile:
    tld: str
    rdap_host: str | None
    backend_key: str | None
    whois_server: str | None
    rdap_ema_ms: float | None
    whois_ema_ms: float | None
    rdap_observations: int
    whois_observations: int
    rate_limits: int
    failures: int
    whois_free_confirmations: int
    whois_evidence_code: str | None
    updated_at: float

    @property
    def whois_can_confirm_unregistered(self) -> bool:
        return self.whois_free_confirmations >= 2

    @property
    def whois_can_confirm_available(self) -> bool:
        """Backward-compatible alias for learned domain-absence capability."""
        return self.whois_can_confirm_unregistered


class RegistryProfileStore:
    """Persist learned registry routing and performance characteristics."""

    def __init__(self, path: str | Path, clock=time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    @staticmethod
    def _tld(value: str) -> str:
        return value.strip().lower().lstrip(".")

    def _initialize(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registry_profiles (
                    tld TEXT PRIMARY KEY,
                    rdap_host TEXT,
                    backend_key TEXT,
                    whois_server TEXT,
                    rdap_ema_ms REAL,
                    whois_ema_ms REAL,
                    rdap_observations INTEGER NOT NULL DEFAULT 0,
                    whois_observations INTEGER NOT NULL DEFAULT 0,
                    rate_limits INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0,
                    whois_free_confirmations INTEGER NOT NULL DEFAULT 0,
                    whois_evidence_code TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.commit()

    def _ensure(self, tld: str) -> None:
        now = self._clock()
        self._conn.execute(
            "INSERT OR IGNORE INTO registry_profiles(tld, updated_at) VALUES(?, ?)",
            (tld, now),
        )

    def get(self, tld: str) -> RegistryProfile | None:
        key = self._tld(tld)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM registry_profiles WHERE tld = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return RegistryProfile(
            tld=key,
            rdap_host=row["rdap_host"],
            backend_key=row["backend_key"],
            whois_server=row["whois_server"],
            rdap_ema_ms=row["rdap_ema_ms"],
            whois_ema_ms=row["whois_ema_ms"],
            rdap_observations=int(row["rdap_observations"]),
            whois_observations=int(row["whois_observations"]),
            rate_limits=int(row["rate_limits"]),
            failures=int(row["failures"]),
            whois_free_confirmations=int(row["whois_free_confirmations"]),
            whois_evidence_code=row["whois_evidence_code"],
            updated_at=float(row["updated_at"]),
        )

    def record_routing(
        self,
        tld: str,
        *,
        rdap_host: str | None = None,
        backend_key: str | None = None,
        whois_server: str | None = None,
    ) -> None:
        key = self._tld(tld)
        with self._lock:
            self._ensure(key)
            self._conn.execute(
                """
                UPDATE registry_profiles
                SET rdap_host = COALESCE(?, rdap_host),
                    backend_key = COALESCE(?, backend_key),
                    whois_server = COALESCE(?, whois_server),
                    updated_at = ?
                WHERE tld = ?
                """,
                (
                    rdap_host,
                    backend_key,
                    whois_server,
                    self._clock(),
                    key,
                ),
            )
            self._conn.commit()

    @staticmethod
    def _ema(previous: float | None, value: float, alpha: float = 0.2) -> float:
        if previous is None:
            return value
        return previous + alpha * (value - previous)

    def record_observation(
        self,
        tld: str,
        protocol: str,
        status: DomainCheckStatus,
        latency_ms: float | None,
    ) -> None:
        if protocol not in {"rdap", "whois"}:
            raise ValueError("protocol must be rdap or whois")
        key = self._tld(tld)
        with self._lock:
            self._ensure(key)
            row = self._conn.execute(
                "SELECT * FROM registry_profiles WHERE tld = ?", (key,)
            ).fetchone()
            assert row is not None
            if protocol == "rdap":
                observations = int(row["rdap_observations"]) + 1
                ema = row["rdap_ema_ms"]
                update_sql = """
                    UPDATE registry_profiles
                    SET rdap_observations = ?, rdap_ema_ms = ?,
                        rate_limits = ?, failures = ?, updated_at = ?
                    WHERE tld = ?
                """
            else:
                observations = int(row["whois_observations"]) + 1
                ema = row["whois_ema_ms"]
                update_sql = """
                    UPDATE registry_profiles
                    SET whois_observations = ?, whois_ema_ms = ?,
                        rate_limits = ?, failures = ?, updated_at = ?
                    WHERE tld = ?
                """
            if latency_ms is not None and status in {
                DomainCheckStatus.AVAILABLE,
                DomainCheckStatus.REGISTRABLE,
                DomainCheckStatus.UNREGISTERED,
                DomainCheckStatus.RESERVED,
                DomainCheckStatus.REGISTERED,
            }:
                ema = self._ema(float(ema) if ema is not None else None, float(latency_ms))

            rate_limits = int(row["rate_limits"]) + int(status is DomainCheckStatus.RATE_LIMITED)
            failures = int(row["failures"]) + int(
                status in {DomainCheckStatus.NETWORK_ERROR, DomainCheckStatus.UNKNOWN}
            )
            self._conn.execute(
                update_sql,
                (observations, ema, rate_limits, failures, self._clock(), key),
            )
            self._conn.commit()

    def record_whois_probe(
        self,
        tld: str,
        status: DomainCheckStatus,
        evidence_code: str | None,
    ) -> None:
        key = self._tld(tld)
        with self._lock:
            self._ensure(key)
            row = self._conn.execute(
                "SELECT whois_free_confirmations FROM registry_profiles WHERE tld = ?",
                (key,),
            ).fetchone()
            assert row is not None
            confirmations = int(row["whois_free_confirmations"])
            if (
                status
                in {
                    DomainCheckStatus.AVAILABLE,
                    DomainCheckStatus.REGISTRABLE,
                    DomainCheckStatus.UNREGISTERED,
                }
                and evidence_code
            ):
                confirmations += 1
            self._conn.execute(
                """
                UPDATE registry_profiles
                SET whois_free_confirmations = ?,
                    whois_evidence_code = COALESCE(?, whois_evidence_code),
                    updated_at = ?
                WHERE tld = ?
                """,
                (confirmations, evidence_code, self._clock(), key),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
