from __future__ import annotations

import re
from dataclasses import dataclass

from domain_finder.domain.models import DomainCheckStatus


@dataclass(frozen=True)
class WhoisEvidence:
    """A conservative semantic conclusion from an authoritative WHOIS reply."""

    status: DomainCheckStatus
    code: str


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


_REGISTRABLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("status_available", r"\bstatus\s*:\s*(?:available|free)\b"),
    ("registration_available", r"\bregistration status\s*:\s*available\b"),
    ("available_yes", r"\bavailable\s*:\s*yes\b"),
    ("domain_available", r"\bdomain\b.{0,160}\bis available for registration\b"),
)

_UNREGISTERED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("domain_not_registered", r"\bdomain (?:is|has) not (?:been )?registered\b"),
    ("domain_not_found", r"\bdomain\b.{0,160}\bnot found\b"),
    ("requested_domain_not_found", r"\brequested domain was not found\b"),
    ("was_not_found", r"\bthe domain\b.{0,160}\bwas not found\b"),
    ("no_matching_record", r"\bno matching record\b"),
    ("no_match", r"\bno match(?:!!| found)?(?:\b|\s+for\b)"),
    ("no_entries", r"\bno entries found\b"),
    ("nothing_found", r"\bnothing found\b"),
    ("no_such_domain", r"\bno such domain\b"),
    ("queried_object_missing", r"\bqueried object does not exist\b"),
    ("object_missing", r"\bobject does not exist\b"),
    ("no_object_found", r"\bno object found\b"),
    ("object_not_found", r"\bobject[_ ]not[_ ]found\b"),
    ("not_found_prefix", r"\bnot found\s*:\s*\S+"),
    ("not_found_exact", r"^not found[.!]?$"),
)

_REGISTERED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("status_registered", r"\bstatus\s*:\s*(?:registered|active|busy)\b"),
    ("registration_busy", r"\bregistration status\s*:\s*(?:busy|registered)\b"),
    ("registrar", r"\bregistrar\s*:"),
    ("creation", r"\b(?:creation date|created)\s*:"),
    ("nameserver", r"\b(?:name server|nameserver)\s*:"),
    ("domain_managers", r"\bdomain managers\b"),
)

_AMBIGUOUS_BLOCKERS = (
    "not indicative of availability",
    "not an indication of availability",
    "failure to locate a record is not indicative",
)


def classify_whois_text(domain: str, text: str) -> WhoisEvidence | None:
    """Classify only explicit registry evidence; policy/disclaimer text stays unknown."""
    if not text or not text.strip():
        return None
    compact = _compact(text)
    blocked = any(marker in compact for marker in _AMBIGUOUS_BLOCKERS)
    if not blocked:
        for code, pattern in _REGISTRABLE_PATTERNS:
            if re.search(pattern, compact, re.IGNORECASE):
                return WhoisEvidence(DomainCheckStatus.REGISTRABLE, code)
        for code, pattern in _UNREGISTERED_PATTERNS:
            if re.search(pattern, compact, re.IGNORECASE):
                return WhoisEvidence(DomainCheckStatus.UNREGISTERED, code)

    try:
        ascii_domain = domain.strip().lower().rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        ascii_domain = domain.strip().lower().rstrip(".")
    if ascii_domain and ascii_domain in compact:
        for code, pattern in _REGISTERED_PATTERNS:
            if re.search(pattern, compact, re.IGNORECASE):
                return WhoisEvidence(DomainCheckStatus.REGISTERED, code)
    return None
