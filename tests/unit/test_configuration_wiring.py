from __future__ import annotations

from domain_finder.cli.commands.run import _create_checker, _create_provider
from domain_finder.infrastructure.config import Settings


def settings() -> Settings:
    return Settings.model_validate(
        {
            "OPENAI_API_KEY": "test-key",  # pragma: allowlist secret
            "HTTP_TIMEOUT": 12.0,
            "RDAP_TIMEOUT": 3.5,
            "MAX_CONNECTIONS": 33,
            "MAX_KEEPALIVE_CONNECTIONS": 11,
            "MAX_RETRIES": 7,
            "RETRY_BACKOFF_MIN": 0.2,
            "RETRY_BACKOFF_MAX": 1.4,
            "MAX_CONCURRENT_LLM_REQUESTS": 5,
            "REGISTRY_PROFILE_FILE": ":memory:",
        }
    )


def test_llm_http_settings_are_wired_to_provider() -> None:
    provider = _create_provider("openai", "test-model", 0.4, 9.0, settings())
    client = provider._http_client
    assert client.timeout == 9.0
    assert client.retries == 7
    assert client.backoff_min == 0.2
    assert client.backoff_max == 1.4
    assert client._limits.max_connections == 33
    assert client._limits.max_keepalive_connections == 11
    assert provider._max_concurrent == 5


def test_rdap_settings_are_wired_to_checker() -> None:
    checker = _create_checker(
        settings=settings(),
        use_rdap=True,
        whois_fallback=False,
        max_workers=17,
        dns_prefilter=False,
    )
    try:
        assert checker.max_workers == 17
        assert checker.rdap_client.timeout == 3.5
        assert checker.rdap_client.max_retries == 7
        assert checker._http_client._transport._pool._max_connections == 33
        assert checker._http_client._transport._pool._max_keepalive_connections == 11
    finally:
        checker.close()


def test_registry_profile_file_is_wired_to_checker(tmp_path) -> None:
    profile_path = tmp_path / "registry-profiles.sqlite3"
    cfg = Settings.model_validate({"REGISTRY_PROFILE_FILE": str(profile_path)})
    checker = _create_checker(
        settings=cfg,
        use_rdap=True,
        whois_fallback=True,
        max_workers=2,
        dns_prefilter=False,
    )
    try:
        assert checker.profile_store is not None
        assert checker.profile_store.path == profile_path
    finally:
        checker.close()
