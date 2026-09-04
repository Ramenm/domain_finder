# Domain Finder Architecture

## Overview

Domain Finder generates domain-name candidates, ranks them locally, and checks registry state while keeping network uncertainty explicit. The CLI remains the primary entry point and delegates generation, checking, caching, and persistence to separate components.

## Domain checking

RDAP is the preferred source. The checker resolves authoritative registry endpoints from the IANA RDAP bootstrap, caches bootstrap data locally, reuses HTTP connections, and groups aliases by canonical registry backend for rate limiting.

Check results use explicit states: `AVAILABLE`, `REGISTERED`, `UNKNOWN`, `RATE_LIMITED`, `NETWORK_ERROR`, `UNSUPPORTED`, and `INVALID`. The compatibility `available` value is `True` or `False` only for definitive outcomes; transport and registry errors remain `None`.

WHOIS is a fallback for inconclusive RDAP results. WHOIS servers are discovered through IANA referrals, and availability is accepted only from conservative, explicit registry evidence such as structured `available/free/not found` responses. Empty or ambiguous WHOIS output never proves availability.

DNS is used only as positive registration evidence. Existing authoritative nameservers can prove a domain is registered; NXDOMAIN or missing NS records never prove that a domain is available.

## Registry adaptation

Registry behavior is learned into a local SQLite profile. The profile stores routing metadata, canonical backend identity, observed latency, rate-limit/failure counters, WHOIS referral information, and confirmed availability evidence. It does not store searched domain names.

Per-backend concurrency and pacing adapt independently. Rate-limit responses reduce pressure on that registry, while sustained definitive responses gradually restore capacity. Batch scheduling interleaves registries so one slow backend cannot occupy every worker.

Registry DNS resolution uses bounded lookups with separate success and failure TTLs so a transient DNS failure is retried instead of poisoning the process for its lifetime.

## Cache

Availability results are stored in SQLite with WAL mode and status-aware TTLs. Definitive and transient states can use different expiry windows, stale rows are ignored, and legacy JSON cache files are import-only.

Runtime SQLite, bootstrap, coverage, virtual-environment, and benchmark-result files are excluded from Git.

## Generation quality

Parallel LLM workers use different deterministic generation strategies rather than identical prompts. Bare labels expand across configured suffixes in input order, JSON responses are parsed when available, and a deterministic local quality scorer ranks candidates before expensive network checks.

Multi-label suffixes and IDN/punycode inputs are normalized before registry checks.

## Testing

The default test suite is offline and deterministic. Network-heavy tests use explicit `network`/`slow` markers. Unit tests cover RDAP status handling, WHOIS evidence parsing, DNS behavior, cache TTLs, registry profiles, concurrency limiting, generation properties, persistence, and configuration wiring.

The benchmark runner verifies known registered domains and only labels random candidates as available after a registry source explicitly confirms the state. It records latency, source, retries, and outcome for reproducible comparisons.

## Safety of availability results

An RDAP/WHOIS result describes registry lookup state, not registrar checkout policy, premium pricing, reservation rules, trademark risk, or guaranteed purchasability. Inconclusive states remain explicit instead of being converted into false `available` or `registered` results.
