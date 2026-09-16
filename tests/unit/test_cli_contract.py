from __future__ import annotations

import inspect

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


def test_wizard_defaults_to_safe_whois_fallback(monkeypatch) -> None:
    prompts: list[tuple[str, object]] = []

    def fake_prompt(text: str, default=None):
        prompts.append((text, default))
        return default

    monkeypatch.setattr(wizard_module.typer, "prompt", fake_prompt)
    monkeypatch.setattr(wizard_module, "run", lambda **kwargs: None)
    wizard_module.wizard()

    defaults = dict(prompts)
    assert defaults["🔄 Use WHOIS as fallback method if RDAP is uncertain? (y/n)"] == "y"


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
