from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from domain_finder.application.dto import DomainSearchRequest, DomainSearchResult
from domain_finder.cli.app import app
from domain_finder.cli.commands import run as run_module
from domain_finder.infrastructure.config import Settings


class FakeProvider:
    display_name = "Mock"
    config = SimpleNamespace(model="mock-model")


class FakeUseCase:
    result: DomainSearchResult

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def execute(self, _request: DomainSearchRequest) -> DomainSearchResult:
        return self.result


class FakeCache:
    def __init__(self, _path: str) -> None:
        pass

    def clear(self) -> None:
        pass


class FakeWriter:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    @staticmethod
    def show_table(*_args, **_kwargs) -> None:
        pass


def install_fakes(monkeypatch, result: DomainSearchResult) -> None:
    FakeUseCase.result = result
    monkeypatch.setattr(run_module, "_create_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(run_module, "_create_checker", lambda **_kwargs: object())
    monkeypatch.setattr(run_module, "CacheManager", FakeCache)
    monkeypatch.setattr(run_module, "ResultWriter", FakeWriter)
    monkeypatch.setattr(run_module, "RunDomainSearchUseCase", FakeUseCase)


def make_result(**overrides) -> DomainSearchResult:
    values = {
        "total_iterations": 1,
        "iterations_attempted": 1,
        "iterations_completed": 1,
        "iterations_failed": 0,
        "total_generated": 1,
        "total_checked": 1,
        "total_available": 0,
        "available_domains": [],
        "total_unregistered": 0,
        "unregistered_domains": [],
        "total_registered": 1,
        "total_reserved": 0,
        "total_inconclusive": 0,
        "total_skipped": 0,
        "results_txt": "results.txt",
        "results_csv": "results.csv",
    }
    values.update(overrides)
    return DomainSearchResult(**values)


def test_zero_completed_iterations_exit_nonzero_without_success(monkeypatch, capsys) -> None:
    install_fakes(
        monkeypatch,
        make_result(
            total_iterations=0,
            iterations_attempted=2,
            iterations_completed=0,
            iterations_failed=2,
            total_generated=0,
            total_checked=0,
            total_registered=0,
        ),
    )
    request = DomainSearchRequest(topic="test", iterations=2)
    settings = Settings.model_validate({"OPENAI_API_KEY": "test-key"})  # pragma: allowlist secret

    with pytest.raises(typer.Exit) as exc:
        run_module._execute_request(request, settings)

    output = capsys.readouterr().out
    assert exc.value.exit_code == 1
    assert "Search failed" in output
    assert "completed successfully" not in output


def test_summary_exposes_registered_reserved_and_inconclusive_counts(monkeypatch, capsys) -> None:
    install_fakes(
        monkeypatch,
        make_result(
            total_generated=6,
            total_checked=6,
            total_available=1,
            total_unregistered=1,
            total_registered=1,
            total_reserved=1,
            total_inconclusive=2,
        ),
    )
    request = DomainSearchRequest(topic="test")
    settings = Settings.model_validate({"OPENAI_API_KEY": "test-key"})  # pragma: allowlist secret

    run_module._execute_request(request, settings)

    output = capsys.readouterr().out
    assert "Registered" in output
    assert "Reserved" in output
    assert "Inconclusive / errors" in output


def test_keyboard_interrupt_is_reported_as_clean_cancellation(monkeypatch, capsys) -> None:
    class InterruptingUseCase(FakeUseCase):
        def execute(self, _request: DomainSearchRequest) -> DomainSearchResult:
            raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "_create_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(run_module, "_create_checker", lambda **_kwargs: object())
    monkeypatch.setattr(run_module, "CacheManager", FakeCache)
    monkeypatch.setattr(run_module, "ResultWriter", FakeWriter)
    monkeypatch.setattr(run_module, "RunDomainSearchUseCase", InterruptingUseCase)

    request = DomainSearchRequest(topic="test")
    settings = Settings.model_validate({"OPENAI_API_KEY": "test-key"})  # pragma: allowlist secret
    with pytest.raises(typer.Exit) as exc:
        run_module._execute_request(request, settings)

    assert exc.value.exit_code == 130
    assert "cancelled" in capsys.readouterr().out.lower()


def test_invalid_environment_is_concise_configuration_error(monkeypatch) -> None:
    monkeypatch.setenv("MAX_RETRIES", "not-an-int")
    result = CliRunner().invoke(app, ["run", "--topic", "test"])

    assert result.exit_code == 2
    assert "Invalid configuration" in result.output
    assert "pydantic" not in result.output.lower()
    assert "traceback" not in result.output.lower()


def test_output_initialization_error_is_concise(monkeypatch, capsys) -> None:
    class BrokenWriter:
        def __init__(self, *_args, **_kwargs) -> None:
            raise OSError("read-only destination")

    monkeypatch.setattr(run_module, "_create_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(run_module, "CacheManager", FakeCache)
    monkeypatch.setattr(run_module, "ResultWriter", BrokenWriter)

    request = DomainSearchRequest(topic="test")
    settings = Settings.model_validate({"OPENAI_API_KEY": "test-key"})  # pragma: allowlist secret
    with pytest.raises(typer.Exit) as exc:
        run_module._execute_request(request, settings)

    output = capsys.readouterr().out
    assert exc.value.exit_code == 2
    assert "Cannot initialize" in output
    assert "read-only destination" in output
    assert "traceback" not in output.lower()


def test_unexpected_programmer_error_is_not_masked(monkeypatch) -> None:
    class BuggyUseCase(FakeUseCase):
        def execute(self, _request: DomainSearchRequest) -> DomainSearchResult:
            raise RuntimeError("programmer bug")

    monkeypatch.setattr(run_module, "_create_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(run_module, "_create_checker", lambda **_kwargs: object())
    monkeypatch.setattr(run_module, "CacheManager", FakeCache)
    monkeypatch.setattr(run_module, "ResultWriter", FakeWriter)
    monkeypatch.setattr(run_module, "RunDomainSearchUseCase", BuggyUseCase)

    request = DomainSearchRequest(topic="test")
    settings = Settings.model_validate({"OPENAI_API_KEY": "test-key"})  # pragma: allowlist secret
    with pytest.raises(RuntimeError, match="programmer bug"):
        run_module._execute_request(request, settings)
