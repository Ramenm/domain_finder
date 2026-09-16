from __future__ import annotations

import inspect

from typer.testing import CliRunner

from domain_finder.cli.app import app
from domain_finder.cli.commands import run as run_module
from domain_finder.cli.commands import wizard as wizard_module
from domain_finder.infrastructure.config import Settings
from domain_finder.infrastructure.llm.openai import OpenAIProvider


def test_run_exposes_symmetric_whois_fallback_toggle() -> None:
    option = inspect.signature(run_module.run).parameters["whois_fallback"].default
    assert option.param_decls == ("--whois-fallback/--no-whois-fallback",)


def test_workers_option_rejects_values_below_one_at_parse_time() -> None:
    option = inspect.signature(run_module.run).parameters["max_workers"].default
    assert option.min == 1


def test_wizard_defaults_to_safe_whois_fallback_and_sqlite_cache(monkeypatch) -> None:
    prompts: list[tuple[str, object]] = []
    captured: dict[str, object] = {}

    def fake_prompt(text: str, default=None, **_kwargs):
        prompts.append((text, default))
        return default

    monkeypatch.setattr(wizard_module.typer, "prompt", fake_prompt)
    monkeypatch.setattr(
        wizard_module,
        "_execute_request",
        lambda request, _settings: captured.update({"request": request}),
    )
    wizard_module.wizard()

    defaults = dict(prompts)
    assert defaults["🔄 Use WHOIS as fallback method if RDAP is uncertain? (y/n)"] == "y"
    request = captured["request"]
    assert request.cache_file == "domains_cache.sqlite3"


def test_custom_ip_endpoint_has_meaningful_provider_display_name() -> None:
    settings = Settings.model_validate(
        {
            "OPENAI_API_KEY": "test-key",  # pragma: allowlist secret
            "OPENAI_BASE_URL": "http://127.0.0.1:8765/v1",
        }
    )
    provider = OpenAIProvider(settings=settings)
    try:
        assert provider.display_name == "127.0.0.1"
    finally:
        provider._http_client.close()


def test_invalid_normalized_tld_fails_before_provider_creation(monkeypatch) -> None:
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be created for invalid input")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # pragma: allowlist secret
    monkeypatch.setattr(run_module, "_create_provider", fail_if_called)

    result = CliRunner().invoke(app, ["run", "--topic", "test", "--tld", "."])

    assert result.exit_code == 2
    assert called is False
    assert "Invalid input" in result.output
    assert "pydantic" not in result.output.lower()


def test_wizard_uses_shared_execution_helper_instead_of_calling_run() -> None:
    source = inspect.getsource(wizard_module.wizard)
    assert "_execute_request(" in source
    assert "\n    run(" not in source
