from __future__ import annotations

import csv
import time
from types import SimpleNamespace

from typer.testing import CliRunner

from domain_finder.cli.app import app
from domain_finder.cli.commands import run as run_module
from domain_finder.domain.errors import ProviderError
from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus, DomainSearchParams


class StaticProvider:
    display_name = "Mock API"
    config = SimpleNamespace(model="mock-model")

    def __init__(self, response: str) -> None:
        self.response = response

    def generate_domains(self, _params: DomainSearchParams) -> str:
        return self.response


class FailingProvider(StaticProvider):
    def generate_domains(self, _params: DomainSearchParams) -> str:
        raise ProviderError("mock provider outage")


class StatusChecker:
    def __init__(self, statuses: dict[str, DomainCheckStatus]) -> None:
        self.statuses = statuses

    def check_domain(self, domain: str) -> DomainCheckResult:
        return self.check_domains([domain])[domain]

    def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        return {
            domain: DomainCheckResult(
                domain=domain,
                status=self.statuses[domain],
                source="unknown"
                if self.statuses[domain]
                in {DomainCheckStatus.UNKNOWN, DomainCheckStatus.NETWORK_ERROR}
                else "rdap",
                checked_at=time.time(),
                detail="mock detail",
            )
            for domain in domains
        }


def invoke_run(monkeypatch, tmp_path, provider, checker, *extra: str):
    monkeypatch.setattr(run_module, "_create_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(run_module, "_create_checker", lambda **_kwargs: checker)
    args = [
        "run",
        "--topic",
        "developer tools",
        "--iterations",
        "1",
        "--per-request",
        "10",
        "--cooldown",
        "0",
        "--cache-file",
        str(tmp_path / "cache.sqlite3"),
        "--results",
        str(tmp_path / "results.txt"),
        "--results-csv",
        str(tmp_path / "results.csv"),
        *extra,
    ]
    return CliRunner().invoke(app, args)


def read_rows(path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_skip_then_real_check_upgrades_stale_report(monkeypatch, tmp_path) -> None:
    provider = StaticProvider("google.com")
    checker = StatusChecker({"google.com": DomainCheckStatus.REGISTERED})

    skipped = invoke_run(monkeypatch, tmp_path, provider, checker, "--skip-check")
    assert skipped.exit_code == 0
    assert read_rows(tmp_path / "results.csv")[0]["status"] == "skipped"

    checked = invoke_run(monkeypatch, tmp_path, provider, checker)
    assert checked.exit_code == 0
    row = read_rows(tmp_path / "results.csv")[0]
    assert row["domain"] == "google.com"
    assert row["status"] == "registered"
    assert row["available"] == "false"
    assert "Registered" in checked.output
    assert "1" in checked.output


def test_full_provider_outage_is_not_reported_as_success(monkeypatch, tmp_path) -> None:
    provider = FailingProvider("")
    checker = StatusChecker({})

    result = invoke_run(monkeypatch, tmp_path, provider, checker)

    assert result.exit_code == 1
    assert "generation failed" in result.output.lower()
    assert "Search failed" in result.output
    assert "completed successfully" not in result.output
    assert "\x1b[" not in result.output


def test_mixed_registry_results_are_visible_and_persisted(monkeypatch, tmp_path) -> None:
    domains = [
        "taken.com",
        "freezone.com",
        "absent.com",
        "reserved.com",
        "unknown.com",
        "errorx.com",
    ]
    statuses = {
        "taken.com": DomainCheckStatus.REGISTERED,
        "freezone.com": DomainCheckStatus.REGISTRABLE,
        "absent.com": DomainCheckStatus.UNREGISTERED,
        "reserved.com": DomainCheckStatus.RESERVED,
        "unknown.com": DomainCheckStatus.UNKNOWN,
        "errorx.com": DomainCheckStatus.NETWORK_ERROR,
    }

    result = invoke_run(
        monkeypatch,
        tmp_path,
        StaticProvider(",".join(domains)),
        StatusChecker(statuses),
    )

    assert result.exit_code == 0
    rows = {row["domain"]: row for row in read_rows(tmp_path / "results.csv")}
    assert set(rows) == set(domains)
    assert rows["taken.com"]["status"] == "registered"
    assert rows["freezone.com"]["status"] == "registrable"
    assert rows["reserved.com"]["status"] == "reserved"
    assert rows["errorx.com"]["status"] == "network_error"
    assert (tmp_path / "results.txt").read_text(encoding="utf-8").splitlines() == ["freezone.com"]
    assert "Inconclusive / errors" in result.output
    assert "generating domain candidates" in result.output
    assert "checking 6 candidate(s)" in result.output


def test_dot_only_tld_fails_before_external_work(monkeypatch, tmp_path) -> None:
    def external_call(*_args, **_kwargs):
        raise AssertionError("external work must not start")

    monkeypatch.setattr(run_module, "_create_provider", external_call)
    result = CliRunner().invoke(app, ["run", "--topic", "test", "--tld", "."])

    assert result.exit_code == 2
    assert "Invalid input" in result.output
    assert "external work" not in result.output


def test_second_run_reuses_cache_without_rechecking_or_false_failure(monkeypatch, tmp_path) -> None:
    provider = StaticProvider("cachedname.com")

    class CountingChecker(StatusChecker):
        calls = 0

        def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
            self.calls += 1
            return super().check_domains(domains)

    checker = CountingChecker({"cachedname.com": DomainCheckStatus.REGISTERED})

    first = invoke_run(monkeypatch, tmp_path, provider, checker)
    second = invoke_run(monkeypatch, tmp_path, provider, checker)

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert checker.calls == 1
    assert "Registered" in second.output
    assert read_rows(tmp_path / "results.csv")[0]["status"] == "registered"
