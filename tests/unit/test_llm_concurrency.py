from __future__ import annotations

from domain_finder.domain.models import ProviderConfig
from domain_finder.infrastructure.llm.base import BaseLLMProvider


class Provider(BaseLLMProvider):
    def _generate_with_prompt(self, prompt: str) -> str:
        return "[]"


def make_provider(limit: int) -> Provider:
    return Provider(
        ProviderConfig(provider="openai", model="test", api_key="test"),  # pragma: allowlist secret
        max_concurrent_requests=limit,
    )


def test_concurrency_limit_is_instance_scoped() -> None:
    one = make_provider(1)
    eight = make_provider(8)
    assert one._semaphore._value == 1
    assert eight._semaphore._value == 8
    assert one._semaphore is not eight._semaphore
