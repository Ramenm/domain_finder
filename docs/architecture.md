# Domain Finder Architecture

## Overview

Domain Finder generates domain-name candidates, ranks them locally, and checks registry state while keeping network uncertainty explicit. The CLI remains the primary entry point and delegates generation, checking, caching, and persistence to separate components.

## Domain checking

RDAP is the preferred source. The checker resolves authoritative registry endpoints from the IANA RDAP bootstrap, caches bootstrap data locally, reuses HTTP connections, and groups aliases by canonical registry backend for rate limiting.

Check results distinguish registry state from purchase eligibility. `REGISTERED` means a domain object exists; `UNREGISTERED` means authoritative RDAP/WHOIS found no object; `RESERVED` means known registry policy blocks ordinary registration; and `REGISTRABLE` requires an explicit positive registration signal. `AVAILABLE` is retained only for legacy compatibility. `UNKNOWN`, `RATE_LIMITED`, `NETWORK_ERROR`, `UNSUPPORTED`, and `INVALID` remain explicit uncertainty/error states. The compatibility `available` value is `True` only for `REGISTRABLE`/legacy `AVAILABLE`, `False` for `REGISTERED`/`RESERVED`, and `None` for `UNREGISTERED` or inconclusive outcomes.

WHOIS is a fallback for inconclusive RDAP results. WHOIS servers are discovered through IANA referrals. Explicit `available/free/available for registration` evidence can establish `REGISTRABLE`, while `not found/no match/no entries` establishes only `UNREGISTERED`. Empty or ambiguous WHOIS output proves neither.

DNS is used only as positive registration evidence. Existing authoritative nameservers can prove a domain is registered; NXDOMAIN or missing NS records never prove that a domain is available.

## Registry adaptation

Registry behavior is learned into a local SQLite profile. The profile stores routing metadata, canonical backend identity, observed latency, rate-limit/failure counters, WHOIS referral information, and learned domain-absence evidence. It does not store searched domain names.

For `.com`, a policy layer checks contractual ICANN/Verisign reserved labels and ICANN's current protected/reserved-name XML after registry absence is established. Policy data is cached locally with stale fallback. A known reservation overrides both `UNREGISTERED` and an overly optimistic `REGISTRABLE` signal.

Per-backend concurrency and pacing adapt independently. Rate-limit responses reduce pressure on that registry, while sustained definitive responses gradually restore capacity. Batch scheduling interleaves registries so one slow backend cannot occupy every worker.

Registry DNS resolution uses bounded lookups with separate success and failure TTLs so a transient DNS failure is retried instead of poisoning the process for its lifetime.

## Cache

Domain-check results are stored in SQLite with WAL mode and status-aware TTLs. Definitive and transient states can use different expiry windows, stale rows are ignored, and legacy JSON cache files are import-only.

Runtime SQLite, bootstrap, coverage, virtual-environment, and benchmark-result files are excluded from Git.

## Generation quality

Parallel LLM workers use different deterministic generation strategies rather than identical prompts. Bare labels expand across configured suffixes in input order, JSON responses are parsed when available, and a deterministic local quality scorer ranks candidates before expensive network checks.

Multi-label suffixes and IDN/punycode inputs are normalized before registry checks.

## Testing

The default test suite is offline and deterministic. Network-heavy tests use explicit `network`/`slow` markers. Unit tests cover RDAP status handling, WHOIS evidence parsing, DNS behavior, cache TTLs, registry profiles, concurrency limiting, generation properties, persistence, and configuration wiring.

The benchmark runner verifies known registered domains and preserves the distinction between registry absence and confirmed registrability. It records latency, source, retries, and outcome for reproducible comparisons.

## Safety of availability results

RDAP 404 or WHOIS `No match` describes registry absence, not guaranteed purchasability. Known reservation policy is checked separately, and only an explicit positive registration signal becomes `REGISTRABLE`. Registrar checkout/EPP may still apply additional eligibility, premium-price, timing, or local policy constraints, so a successful registrar/EPP check remains the strongest purchase-time confirmation.
