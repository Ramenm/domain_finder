# User Journey and Truthful Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CLI and wizard validate inputs consistently, show visible progress, report every checked outcome truthfully, and never label a zero-work run successful.

**Architecture:** Move request validation into `DomainSearchRequest`, add progress events emitted by the use case, persist every check result through one CSV upsert path, and keep terminal presentation in the CLI layer. `results.txt` stays backward-compatible while `results.csv` becomes the authoritative per-domain report.

**Tech Stack:** Python 3.10+, Pydantic 2, Typer/Click, Rich, pytest, SQLite-backed cache.

**Spec:** `docs/superpowers/specs/2026-09-16-user-journey-hardening-design.md`

## Global Constraints

- Preserve conservative registrability semantics: `UNREGISTERED` is not guaranteed purchasability.
- Stable supported Python versions remain 3.10 through 3.14; 3.15 prerelease remains advisory.
- `results.txt` contains confirmed registrable domains, except `--skip-check` where it remains the generated-name list.
- Expected user/config/filesystem failures must not expose internal tracebacks.
- Partial useful work is preserved and reported; zero successful generation iterations exit non-zero.
- No GUI, registrar purchase automation, second LLM protocol, or PyPI publication in this plan.

---

### Task 1: Shared request validation

**Files:**
- Modify: `domain_finder/application/dto.py`
- Modify: `domain_finder/cli/commands/run.py`
- Modify: `domain_finder/cli/commands/wizard.py`
- Test: `tests/unit/test_cli_contract.py`
- Create: `tests/unit/test_request_validation.py`

**Interfaces:**
- Produces: validated `DomainSearchRequest` with normalized `tlds` and existing field names.
- Consumes: Typer/Click values from both direct CLI and wizard.

- [ ] **Step 1: Write failing validation tests** for empty/dot-only TLDs, zero workers/iterations, invalid temperature/timeout, and `min_len > max_len`.
- [ ] **Step 2: Run** `pytest tests/unit/test_request_validation.py tests/unit/test_cli_contract.py -q` and confirm the new cases fail.
- [ ] **Step 3: Convert `DomainSearchRequest` to a Pydantic model** with explicit `Field` constraints and a model validator that normalizes TLDs and rejects empty normalized suffixes or `min_len > max_len`.
- [ ] **Step 4: Build the validated request before provider/network creation** in `run.py`; catch `pydantic.ValidationError` and print one concise `Invalid input:` message before `typer.Exit(2)`.
- [ ] **Step 5: Make wizard prompts typed/bounded** and construct the same `DomainSearchRequest`; use `domains_cache.sqlite3` and remove the duplicate header path by invoking a shared execution helper instead of calling `run()` recursively.
- [ ] **Step 6: Re-run focused tests** and commit `fix: validate user search requests consistently`.

### Task 2: Authoritative result persistence

**Files:**
- Modify: `domain_finder/infrastructure/persistence.py`
- Modify: `domain_finder/application/use_cases.py`
- Test: `tests/unit/test_persistence.py`
- Test: `tests/unit/test_pipeline_registrability.py`
- Test: `tests/unit/test_skip_check_semantics.py`

**Interfaces:**
- Produces: `ResultWriter.append_check_results(results: Iterable[DomainCheckResult]) -> None`.
- CSV schema: `domain,status,available,source,checked_at,detail`.
- Existing `append_available()` remains as a compatibility wrapper where tests or callers still use it.

- [ ] **Step 1: Add failing persistence tests** proving registered/reserved/unregistered/error results are written and a later definitive result overwrites an older `skipped` row.
- [ ] **Step 2: Run** `pytest tests/unit/test_persistence.py tests/unit/test_skip_check_semantics.py -q` and confirm the stale-row regression fails.
- [ ] **Step 3: Expand CSV normalization/migration** so legacy rows without `status`/`detail` remain readable; infer `registrable` from legacy `available=true` and `skipped` from legacy `source=skipped`.
- [ ] **Step 4: Implement `append_check_results`** to upsert every result, serialize tri-state availability as `true`/`false`/blank, and add only registrable results to the TXT file.
- [ ] **Step 5: Change the use case** to pass all returned check results to `append_check_results`, not only positive results.
- [ ] **Step 6: Re-run focused tests** and commit `fix: persist every domain check outcome`.

### Task 3: Complete result accounting and truthful exit semantics

**Files:**
- Modify: `domain_finder/application/dto.py`
- Modify: `domain_finder/application/use_cases.py`
- Modify: `domain_finder/cli/commands/run.py`
- Test: `tests/unit/test_pipeline_registrability.py`
- Create: `tests/unit/test_cli_outcomes.py`

**Interfaces:**
- `DomainSearchResult` adds `total_checked`, `total_skipped`, `total_registered`, `total_reserved`, and `total_inconclusive` while retaining existing fields.
- Partial success: at least one completed generation iteration returns normally with a warning if some iterations failed.
- Total generation failure: CLI prints a failure summary then exits `1`.

- [ ] **Step 1: Write failing result-accounting tests** with mixed `REGISTRABLE`, `UNREGISTERED`, `REGISTERED`, `RESERVED`, `UNKNOWN`, and `NETWORK_ERROR` results.
- [ ] **Step 2: Write a failing CLI test** proving zero completed generation iterations cannot print success or exit `0`.
- [ ] **Step 3: Run the focused tests** and confirm both failures reproduce current behavior.
- [ ] **Step 4: Count all statuses in the use case** without changing status semantics; classify unknown/rate-limited/network-error/unsupported/invalid as `total_inconclusive`.
- [ ] **Step 5: Expand the terminal summary** with checked, registered, reserved, inconclusive/errors, skipped/unverified, and attempted/completed/failed iteration rows.
- [ ] **Step 6: Add final outcome logic**: zero completed iterations -> concise failure + exit `1`; partial iteration failure -> yellow warning + exit `0`; full useful success -> green success.
- [ ] **Step 7: Re-run focused tests** and commit `fix: report complete search outcomes truthfully`.

### Task 4: Progress visibility and clean interruption

**Files:**
- Modify: `domain_finder/application/dto.py`
- Modify: `domain_finder/application/use_cases.py`
- Modify: `domain_finder/cli/commands/run.py`
- Create: `tests/unit/test_progress_reporting.py`
- Extend: `tests/unit/test_cli_outcomes.py`

**Interfaces:**
- Produce `SearchProgress` with fields `phase`, `iteration`, `iterations`, `count`, and optional `message`.
- `RunDomainSearchUseCase(..., progress_callback: Callable[[SearchProgress], None] | None = None)` emits phase-level events only.

- [ ] **Step 1: Write failing callback tests** for generation start/finish, checking start/finish, and failed generation iteration events.
- [ ] **Step 2: Run** `pytest tests/unit/test_progress_reporting.py -q` and confirm failure.
- [ ] **Step 3: Emit progress events** around slow generation/checking boundaries without one-event-per-domain spam.
- [ ] **Step 4: Add a CLI presenter** that prints concise phase lines; rely on Rich terminal detection so redirected output stays ANSI-free.
- [ ] **Step 5: Catch `KeyboardInterrupt` at the CLI boundary**, print `Search cancelled by user.`, preserve exit code `130`, and do not print an internal traceback.
- [ ] **Step 6: Re-run progress/outcome tests** and commit `feat: show search progress and clean cancellation`.

### Task 5: Expected-error presentation

**Files:**
- Modify: `domain_finder/cli/commands/run.py`
- Modify: `domain_finder/cli/commands/wizard.py`
- Extend: `tests/unit/test_cli_outcomes.py`
- Extend: `tests/unit/test_cli_contract.py`

**Interfaces:**
- Validation/configuration/provider/filesystem failures use exit code `2` when startup/input is invalid.
- Execution/network failures use exit code `1` when work started but could not complete.
- No expected failure path prints a Rich traceback.

- [ ] **Step 1: Write failing CLI tests** for invalid environment values and output-path initialization failures, asserting concise text and absence of `Traceback`, `pydantic`, and internal source frames.
- [ ] **Step 2: Run focused tests** and confirm the current raw traceback behavior fails them.
- [ ] **Step 3: Catch settings `ValidationError`, `OSError`, and known provider errors** at initialization boundaries and map them to actionable one-line messages.
- [ ] **Step 4: Narrow the execution exception handler** so expected domain/provider/network failures are concise while unexpected programmer errors remain test-visible instead of being falsely labeled as user errors.
- [ ] **Step 5: Re-run focused tests** and commit `fix: present expected CLI failures cleanly`.

### Task 6: User-facing regression suite and documentation

**Files:**
- Create: `tests/integration/test_cli_user_journey.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Integration tests invoke Typer's CLI runner with a deterministic local/fake provider boundary and temporary output paths.
- Coverage includes repeat-run stale CSV, skip-check, full provider failure, mixed result statuses, and wizard defaults.

- [ ] **Step 1: Add integration regression tests** reproducing the audited user journeys, especially `skipped -> registered` report upgrade and all-generation-failed exit behavior.
- [ ] **Step 2: Run** `pytest tests/integration/test_cli_user_journey.py -q` and confirm all new scenarios pass with the implemented behavior.
- [ ] **Step 3: Update README** with CSV status columns, exit behavior, partial-success wording, and the fact that progress is phase-level rather than per-domain.
- [ ] **Step 4: Update architecture docs** to describe the authoritative report contract and shared request validation boundary.
- [ ] **Step 5: Run full offline verification**: `pytest -q`, `pre-commit run --all-files`, `python -m pip check`, and `pip-audit`.
- [ ] **Step 6: Run the existing live network suite** with `pytest -m "network and slow"` because persistence/reporting touches live result handling.
- [ ] **Step 7: Commit** `test: cover end-to-end user reporting flows`.

### Task 7: PR integration gate

**Files:**
- No new product files unless CI exposes a regression.

- [ ] **Step 1: Push the feature branch and create a PR** against protected `master` with an audit-derived summary and exact verification evidence.
- [ ] **Step 2: Wait for protected checks** `quality`, `tests (3.10)`, `tests (3.11)`, `tests (3.12)`, `tests (3.13)`, and `tests (3.14)`; inspect the 3.15 prerelease advisory job too.
- [ ] **Step 3: If CI exposes a failure, reproduce locally where possible, add/fix a regression test, and push only after local verification.**
- [ ] **Step 4: Run manual live-network workflow on the PR head** and require success before merge.
- [ ] **Step 5: Merge through the protected PR, update local `master`, prune the feature branch, and verify post-merge CI on the merge commit.**
- [ ] **Step 6: Verify `master == origin/master`, clean worktree, one remote `master` head, and unchanged branch-protection requirements.**

## Self-review

- Spec coverage: PR 1 requirements for shared validation, wizard cleanup, complete CSV, complete summary, failure semantics, progress, interruption, and expected-error handling are each mapped to Tasks 1-6.
- Deferred by design: HTTP retry internals, cross-platform installed-wheel E2E, Dependabot/CodeQL/release automation belong to later plans/PRs from the parent spec.
- Placeholder scan: no TODO/TBD or unspecified implementation steps remain.
- Type consistency: `DomainSearchRequest`, `DomainSearchResult`, `SearchProgress`, and `ResultWriter.append_check_results()` are named consistently across tasks.
