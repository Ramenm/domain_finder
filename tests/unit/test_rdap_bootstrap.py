from __future__ import annotations

import json
from pathlib import Path

import httpx

from domain_finder.infrastructure.whois.rdap_bootstrap import RdapBootstrap


def test_bootstrap_downloads_and_caches_authoritative_services(tmp_path: Path) -> None:
    payload = {"services": [[["com", "net"], ["https://rdap.example/"]]]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://data.iana.org/rdap/dns.json"
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = tmp_path / "bootstrap.json"
    bootstrap = RdapBootstrap(cache_path=cache, http_client=client, ttl_seconds=3600)

    assert bootstrap.get_base_urls_for_domain("Example.COM") == ("https://rdap.example/",)
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["services"]["com"] == ["https://rdap.example/"]


def test_bootstrap_uses_fresh_disk_cache_without_network(tmp_path: Path) -> None:
    cache = tmp_path / "bootstrap.json"
    cache.write_text(
        json.dumps({"loaded_at": 4_000_000_000.0, "services": {"io": ["https://rdap.io/"]}}),
        encoding="utf-8",
    )

    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network should not be used: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(fail_handler))
    bootstrap = RdapBootstrap(cache_path=cache, http_client=client, ttl_seconds=3600)
    assert bootstrap.get_base_urls_for_domain("name.io") == ("https://rdap.io/",)


def test_bootstrap_returns_none_for_invalid_or_unknown_tld(tmp_path: Path) -> None:
    cache = tmp_path / "bootstrap.json"
    cache.write_text(
        json.dumps({"loaded_at": 4_000_000_000.0, "services": {"com": ["https://rdap.example/"]}}),
        encoding="utf-8",
    )
    bootstrap = RdapBootstrap(cache_path=cache, ttl_seconds=3600)
    assert bootstrap.get_base_urls_for_domain("nodot") is None
    assert bootstrap.get_base_urls_for_domain("name.unknown") is None
