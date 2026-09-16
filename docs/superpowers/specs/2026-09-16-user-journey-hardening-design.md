# Domain Finder User-Journey Hardening Design

Date: 2026-09-16
Status: proposed and audited against current `master`

## Goal

Make Domain Finder truthful, visible, and predictable from the user's point of view, not only internally correct. A user should always understand what the program is doing, whether useful work completed, where every checked domain ended up, and what to do when configuration, network, provider, filesystem, or registry operations fail.

This design also hardens the shared HTTP layer and turns the important user journeys into executable end-to-end tests across supported Python versions.

## Current audited behavior

The audit used the installed `domain-finder` entry point, `python -m domain_finder`, scripted wizard input, a local OpenAI-compatible mock server, real RDAP checks, repeated runs against the same output files, narrow terminals, non-TTY output, invalid configuration, filesystem failures, and Ctrl+C.

Observed problems:

- If all LLM generation attempts fail, the command exits `0` and prints `Search completed successfully` with zero completed iterations.
- `--tld .` is accepted and can end successfully with zero generated domains.
- `min_len > max_len`, invalid temperature, and invalid environment values can expose raw Pydantic validation text or full Rich tracebacks.
- An unwritable output path currently exposes a full internal traceback.
- Wizard accepts negative iteration counts and can report success after doing zero work.
- Wizard prints the application header twice and still uses a cache filename ending in `.json` for a SQLite cache.
- Normal checked runs persist only a subset of outcomes to `results.csv`; registered, reserved, unknown, and many error outcomes are invisible there.
- A repeated workflow can leave stale output: `google.com` was first saved as `skipped`; a later real RDAP run correctly cached it as `registered`, but `results.csv` still said `skipped`.
- The final CLI summary shows registrable and unregistered counts but not registered, reserved, unknown, rate-limited, network-error, unsupported, or invalid counts.
- During a slow provider request the UI can be completely silent after the provider line. A measured 3-second mock delay produced about 3.1 seconds with no user-visible progress.
- Sequential real registry checking similarly has a visible quiet gap with no progress indication.
- Ctrl+C exits with code 130 without a traceback, which is correct, but the user receives no explicit cancellation message.
- At a 50-column terminal width the generated option help is heavily truncated, including long flag names.
- Piped/non-TTY help is clean and contains no ANSI escape sequences.
- Both console-script and `python -m domain_finder` entry points work, but startup for help is about 0.7 seconds on the audited Ubuntu machine.

## Design principles

1. Truth before optimism: never call a zero-work or fully failed run successful.
2. Every checked candidate must have a visible final status in the machine-readable report.
3. UI progress must describe phases without flooding the terminal or changing core semantics.
4. CLI and wizard must share one validation contract.
5. Expected user/configuration/filesystem/network failures get concise messages and stable exit codes; tracebacks stay for explicit debug/developer use only.
6. Existing conservative registrability semantics remain unchanged: registry absence is not promoted to purchasability.
7. Changes are split into independently reviewable PRs so user-facing behavior, networking, E2E, and repository automation do not hide each other's regressions.

## User-facing result contract

`results.txt` remains intentionally narrow: confirmed registrable domains only, except `--skip-check`, where it remains the generated-name list for backward compatibility.
`results.csv` becomes the authoritative session/report surface for all candidates processed by the run. Each row is an upsert by domain and contains at least:

- `domain`
- `status`
- `available`
- `source`
- `checked_at`
- `detail`

A later definitive check replaces an earlier `skipped`/unknown row. A confirmed registered or reserved result must never leave an older unchecked row visible.

The final terminal summary shows counts for: generated, checked, registrable, unregistered, registered, reserved, inconclusive/errors, and skipped/unverified. It also shows attempted/completed/failed iterations when failures occurred.

If no useful generation iteration completes, the command exits non-zero and says generation failed rather than printing success. Partial success remains possible: completed work is preserved, the summary explains failed iterations, and the exit behavior is documented and tested.

## Validation and error experience

Introduce one request-validation boundary before expensive work. Direct CLI options retain Typer range validation where possible; cross-field and normalized-value validation happens before provider/network/filesystem work.

Validation covers non-empty normalized TLDs, supported provider, positive timeout, temperature range, valid worker counts, iteration/count bounds, `min_len <= max_len`, and output/cache paths that can be initialized.

Wizard reuses the same validated request construction rather than maintaining a looser parallel contract. It uses bounded typed prompts where practical, one header, and the SQLite cache default used by `run`.

Expected failures are mapped to concise categories: configuration, provider, validation, filesystem, network/registry, and interrupted. User output includes the actionable cause without internal stack frames. Developer tracebacks can be made available through an explicit debug mode later; debug mode is not required for the first implementation block.
## Progress and perceived latency

Long operations need visible phase-level feedback. The CLI should show generation and checking phases, iteration number, and checked/generated counts. Progress must remain useful in both TTY and non-TTY contexts: interactive terminals may use Rich status/progress rendering, while redirected output uses simple line events without control sequences.

The UI must not print one line per domain by default. The goal is to eliminate unexplained silence, not create log spam. A slow LLM call should visibly say that generation is in progress; registry checking should similarly expose that a batch is being checked.

Terminal output is designed for normal 80+ column use, while narrow terminals must remain understandable. Help text should prefer shorter descriptions and aliases rather than relying on wide tables for essential meaning.

Ctrl+C remains exit code 130 and gains a concise cancellation message. Partial files already flushed before cancellation remain valid and parseable.

## HTTP reliability block

The shared `HttpClient` gets deterministic offline tests using `httpx.MockTransport` or equivalent injection. Tests cover successful JSON responses, 429, `Retry-After`, retryable 5xx responses, non-retryable 4xx responses, timeouts/transport errors, exhausted retries, SSE streaming, malformed stream chunks, `[DONE]`, and resource closing.

Normal and streaming request paths use the same retry policy. Retryable 5xx responses back off, 429 respects a valid `Retry-After` value when present, and exhausted rate limiting produces a meaningful `ProviderError` instead of a message ending with `None`.

Retry-count normalization prevents zero configured retries from accidentally producing no request attempts. No change is made to RDAP's separate registry-specific adaptive throttling unless a failing test proves an interaction problem.

## End-to-end user journeys

Add executable user-level tests around the installed CLI, not only internal function calls. Scenarios include help/entry points, missing API key, invalid CLI values, invalid environment values, unwritable output paths, wizard defaults and validation, skip-check, repeated output-file reuse, full provider outage, partial LLM-worker failure, empty/duplicate generation, mixed registry statuses, cache reuse, and clean interruption behavior where practical.
The E2E suite uses a local OpenAI-compatible mock for deterministic generation and keeps real RDAP/WHOIS tests in the existing explicit live-network workflow. It verifies both terminal-visible text/exit codes and persisted report contents.

Packaging smoke tests build wheel and sdist, install the wheel into a clean environment, and run both `domain-finder --help` and `python -m domain_finder --help`. Cross-platform smoke coverage should include Ubuntu, Windows, and macOS for installation/CLI startup; the expensive full test matrix remains Linux unless platform-specific failures justify expansion.

## Repository security and maintenance

After behavior and E2E are stable, add repository-level maintenance as a separate PR:

- Dependabot updates for Python dependencies and GitHub Actions.
- Enable Dependabot security alerts/updates where repository settings permit it.
- CodeQL Python scanning on pull requests and a scheduled cadence.
- `SECURITY.md` with a clear vulnerability-reporting path.
- Package metadata URLs for source/issues and other useful metadata.
- A release-check workflow triggered by tags that builds wheel/sdist, installs the built wheel in a clean environment, and runs CLI smoke tests.

Automatic PyPI publication is explicitly out of scope until trusted publishing/credentials and a release policy are intentionally configured.

## Delivery sequence

1. **PR 1 — user journey and truthful reporting:** shared validation, wizard cleanup, complete CSV result upserts, complete terminal status summary, failure/partial-success semantics, progress visibility, clean expected-error handling.
2. **PR 2 — HTTP reliability:** retry/backoff/Retry-After/streaming fixes and focused offline tests.
3. **PR 3 — E2E and packaging:** installed-CLI user flows, repeated-run regressions, clean wheel install, and cross-platform smoke checks.
4. **PR 4 — security and release hygiene:** Dependabot, CodeQL, security policy, package metadata, and release-check automation.

Each PR passes the existing protected stable Python matrix (3.10 through 3.14), quality checks, and the 3.15 prerelease signal. Network-sensitive changes also receive the manual live-network workflow before merge.
## Acceptance criteria

The work is complete when all of the following are demonstrably true:

- A run with zero successful generation iterations cannot end with a success message or success exit code.
- Every checked/generated candidate represented by the session report has a current status; a later check upgrades stale `skipped` rows.
- Registered/reserved/inconclusive outcomes are visible in both summary counts and CSV, not silently discarded.
- Invalid CLI/wizard/environment/path inputs produce concise actionable errors without internal Rich/Pydantic tracebacks.
- Wizard and direct mode share defaults and validation, and wizard does not duplicate the header or use a misleading JSON cache filename.
- A user sees phase progress during slow generation/checking and redirected output remains plain and machine-safe.
- Ctrl+C remains a clean interruption with valid persisted data and an understandable message.
- HTTP retry tests prove correct behavior for 429, Retry-After, 5xx, transport errors, exhausted retries, and streaming.
- Repeated-run E2E tests reproduce and prevent the stale-report bug found during this audit.
- Built distributions install and launch from a clean environment; supported-platform CLI smoke tests pass.
- Protected CI remains green and no existing registrability-safety semantics are weakened.

## Non-goals

This phase does not add a graphical/web UI, registrar purchase automation, or a second LLM protocol. It does not reinterpret RDAP/WHOIS absence as guaranteed availability. It does not publish packages automatically to PyPI.

Performance work is limited to user-visible responsiveness and regressions discovered by measurement. Large algorithmic rewrites or speculative optimization are deferred unless profiling identifies a concrete bottleneck.
