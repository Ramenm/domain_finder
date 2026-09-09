"""Registry policy checks that are distinct from registration-state lookups."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from defusedxml import ElementTree as ET

ICANN_GLOBAL_RESERVED_URL = (
    "https://www.icann.org/sites/default/files/packages/reserved-names/ReservedNames.xml"
)
ICANN_COM_AGREEMENT_URL = "https://itp.cdn.icann.org/en/files/registry-agreements/com/com-agreement-html-01-12-2024-en.htm"

# Appendix 6 labels whose reservation is intrinsic to the .com registry contract.
_COM_CONTRACT_RESERVED = frozenset(
    {
        "afrinic",
        "apnic",
        "arin",
        "aso",
        "ccnso",
        "example",
        "gnso",
        "gtld-servers",
        "iab",
        "iana",
        "iana-servers",
        "icann",
        "iesg",
        "ietf",
        "internic",
        "irtf",
        "istf",
        "lacnic",
        "latnic",
        "nic",
        "rfc-editor",
        "ripe",
        "root-servers",
        "whois",
        "www",
    }
)


@dataclass(frozen=True)
class ReservedNameMatch:
    """Evidence that registry policy blocks ordinary registration of a label."""

    source: str
    detail: str


class ReservedNamePolicy:
    """Resolve known registry-policy reservations with a stale-safe XML cache."""

    def __init__(
        self,
        cache_path: str | Path = ".icann_reserved_names.xml",
        *,
        ttl: float = 7 * 24 * 60 * 60,
        http_client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.ttl = ttl
        self.http_client = http_client
        self._clock = clock
        self._lock = threading.RLock()
        self._global_labels: frozenset[str] | None = None

    @staticmethod
    def _parts(domain: str) -> tuple[str, str] | None:
        try:
            normalized = domain.strip().lower().rstrip(".").encode("idna").decode("ascii")
        except UnicodeError:
            return None
        if normalized.count(".") != 1:
            return None
        label, tld = normalized.split(".", 1)
        if not label or not tld:
            return None
        return label, tld

    @staticmethod
    def _parse_labels(payload: bytes) -> frozenset[str]:
        root = ET.fromstring(payload)
        labels: set[str] = set()

        def local_name(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        for record in root.iter():
            if local_name(record.tag) != "record":
                continue
            for child in record:
                if local_name(child.tag) not in {"label1", "label2"}:
                    continue
                if child.text and (normalized := child.text.strip().lower()):
                    labels.add(normalized)
        return frozenset(labels)

    def _cached_payload(self) -> bytes | None:
        try:
            return self.cache_path.read_bytes()
        except OSError:
            return None

    def _cache_is_fresh(self) -> bool:
        try:
            age = self._clock() - self.cache_path.stat().st_mtime
        except OSError:
            return False
        return age <= self.ttl

    def _fetch_payload(self) -> bytes | None:
        owns_client = self.http_client is None
        client = self.http_client or httpx.Client(timeout=10, follow_redirects=True)
        try:
            response = client.get(
                ICANN_GLOBAL_RESERVED_URL,
                headers={"User-Agent": "domain-finder/2"},
                timeout=10,
            )
            response.raise_for_status()
            payload = bytes(response.content)
            self._parse_labels(payload)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_name(f"{self.cache_path.name}.tmp")
            tmp.write_bytes(payload)
            tmp.replace(self.cache_path)
            return payload
        except (httpx.HTTPError, OSError, ET.ParseError):
            return None
        finally:
            if owns_client:
                client.close()

    def _global_reserved_labels(self) -> frozenset[str]:
        with self._lock:
            if self._global_labels is not None:
                return self._global_labels
            stale = self._cached_payload()
            payload = (
                stale if stale is not None and self._cache_is_fresh() else self._fetch_payload()
            )
            if payload is None:
                payload = stale
            if payload is None:
                self._global_labels = frozenset()
                return self._global_labels
            try:
                self._global_labels = self._parse_labels(payload)
            except ET.ParseError:
                self._global_labels = frozenset()
            return self._global_labels

    def match(self, domain: str) -> ReservedNameMatch | None:
        """Return policy evidence when ordinary registration is known to be blocked."""
        parts = self._parts(domain)
        if parts is None:
            return None
        label, tld = parts
        if tld != "com":
            return None
        if label in _COM_CONTRACT_RESERVED:
            return ReservedNameMatch(
                source="icann-com-registry-agreement",
                detail=f"{label}.com is reserved by the .com registry agreement: {ICANN_COM_AGREEMENT_URL}",
            )
        if label in self._global_reserved_labels():
            return ReservedNameMatch(
                source="icann-global-reserved-names",
                detail=f"{label} is present in ICANN's protected/reserved labels: {ICANN_GLOBAL_RESERVED_URL}",
            )
        return None
