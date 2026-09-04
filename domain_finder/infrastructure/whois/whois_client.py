from __future__ import annotations

import re
import socket
import time
from functools import lru_cache

import whois

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.infrastructure.whois.registry_profiles import RegistryProfileStore
from domain_finder.infrastructure.whois.whois_evidence import classify_whois_text


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _to_ascii_domain(domain: str) -> str:
    normalized = domain.strip().lower().rstrip(".")
    return normalized.encode("idna").decode("ascii")


def _socket_query(server: str, query: str, timeout: float = 3.0) -> str:
    chunks: list[bytes] = []
    total = 0
    with socket.create_connection((server, 43), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((query + "\r\n").encode("ascii"))
        while total < 262_144:
            try:
                chunk = sock.recv(min(65_535, 262_144 - total))
            except TimeoutError:
                break
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


@lru_cache(maxsize=512)
def _iana_whois_server(tld: str) -> str | None:
    response = _socket_query("whois.iana.org", tld)
    for line in response.splitlines():
        if line.lower().startswith("whois:"):
            server = line.split(":", 1)[1].strip()
            return server or None
    return None


def _raw_whois(domain: str) -> str | None:
    ascii_domain = _to_ascii_domain(domain)
    tld = ascii_domain.rsplit(".", 1)[-1]
    server = _iana_whois_server(tld)
    if not server:
        return None
    return _socket_query(server, ascii_domain)


class WhoisClient:
    """WHOIS client with conservative raw-IANA fallback for ccTLD gaps."""

    def __init__(
        self,
        raw_fallback: bool = False,
        profile_store: RegistryProfileStore | None = None,
    ) -> None:
        self.raw_fallback = raw_fallback
        self.profile_store = profile_store

    def supports_availability(self, domain: str) -> bool:
        """Return whether authoritative raw WHOIS discovery is enabled."""
        return self.raw_fallback and "." in _to_ascii_domain(domain)

    def _raw_status(self, domain: str) -> DomainCheckStatus | None:
        if not self.raw_fallback:
            return None
        ascii_domain = _to_ascii_domain(domain)
        tld = ascii_domain.rsplit(".", 1)[-1]
        if self.profile_store is not None:
            try:
                server = _iana_whois_server(tld)
            except (OSError, UnicodeError):
                server = None
            if server:
                self.profile_store.record_routing(tld, whois_server=server)
        try:
            raw = _raw_whois(domain)
        except (OSError, UnicodeError):
            return None
        if not raw:
            return None
        evidence = classify_whois_text(domain, raw)
        if (
            evidence is not None
            and evidence.status is DomainCheckStatus.AVAILABLE
            and self.profile_store is not None
        ):
            self.profile_store.record_whois_probe(tld, evidence.status, evidence.code)
        return evidence.status if evidence is not None else None

    @staticmethod
    def _parsed_status_text(value) -> str:
        if isinstance(value, (list, tuple, set)):
            return " ".join(str(item) for item in value)
        return str(value or "")

    @staticmethod
    def _parsed_explicitly_available(status_text: str) -> bool:
        normalized = _compact(status_text)
        if "not available" in normalized:
            return False
        return bool(re.search(r"\b(?:available|free)\b", normalized))

    def check_domain(self, domain: str) -> DomainCheckResult:
        """Check domain while preferring authoritative raw evidence for known zones."""
        started = time.monotonic()
        original_status = DomainCheckStatus.UNKNOWN
        original_detail: str | None = None
        raw_attempted = False
        raw_value: DomainCheckStatus | None = None

        ascii_domain = _to_ascii_domain(domain)
        tld = ascii_domain.rsplit(".", 1)[-1]

        def result(status: DomainCheckStatus, detail: str | None = None) -> DomainCheckResult:
            latency_ms = (time.monotonic() - started) * 1000
            if self.profile_store is not None:
                self.profile_store.record_observation(tld, "whois", status, latency_ms)
            return DomainCheckResult(
                domain=domain,
                status=status,
                source="whois",
                checked_at=time.time(),
                detail=detail,
                latency_ms=latency_ms,
            )

        def raw_status() -> DomainCheckStatus | None:
            nonlocal raw_attempted, raw_value
            if not raw_attempted:
                raw_attempted = True
                raw_value = self._raw_status(domain)
            return raw_value

        # For zones with verified raw semantics, avoid doing the same WHOIS
        # lookup twice through python-whois and then the authoritative server.
        if self.raw_fallback and self.supports_availability(domain):
            status = raw_status()
            if status is not None:
                return result(status, "raw authoritative WHOIS provided definitive evidence")

        try:
            data = whois.whois(_to_ascii_domain(domain))

            def get_value(attr: str):
                if isinstance(data, dict):
                    return data.get(attr)
                return getattr(data, attr, None)

            status_text = self._parsed_status_text(get_value("status"))
            parsed_evidence = classify_whois_text(domain, status_text)
            parser_available = self._parsed_explicitly_available(status_text)
            if parser_available or (
                parsed_evidence is not None
                and parsed_evidence.status is DomainCheckStatus.AVAILABLE
            ):
                evidence_code = (
                    parsed_evidence.code
                    if parsed_evidence is not None
                    else "parser_status_available"
                )
                if self.profile_store is not None:
                    self.profile_store.record_whois_probe(
                        tld, DomainCheckStatus.AVAILABLE, evidence_code
                    )
                return result(
                    DomainCheckStatus.AVAILABLE,
                    "WHOIS parser reported explicit availability",
                )

            strong_registered = bool(
                get_value("creation_date")
                or get_value("emails")
                or get_value("registrar")
                or get_value("name_servers")
                or (status_text and "not registered" not in _compact(status_text))
            )
            domain_name = get_value("domain_name")
            if strong_registered:
                return result(DomainCheckStatus.REGISTERED)

            if domain_name:
                status = raw_status()
                if status is not None:
                    return result(status, "raw WHOIS disambiguated weak parser result")
                original_detail = "domain_name-only WHOIS response is inconclusive"
            else:
                original_detail = "empty WHOIS response is inconclusive"
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            evidence = classify_whois_text(domain, message)
            if evidence is not None and evidence.status is DomainCheckStatus.AVAILABLE:
                if self.profile_store is not None:
                    self.profile_store.record_whois_probe(
                        tld, DomainCheckStatus.AVAILABLE, evidence.code
                    )
                return result(
                    DomainCheckStatus.AVAILABLE,
                    f"WHOIS reported explicit availability ({evidence.code})",
                )
            original_status = DomainCheckStatus.NETWORK_ERROR
            original_detail = message[:512]

        status = raw_status()
        if status is not None:
            return result(status, "raw authoritative WHOIS provided definitive evidence")
        return result(original_status, original_detail)
