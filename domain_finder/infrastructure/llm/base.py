"""Base LLM provider implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from domain_finder.domain.errors import ProviderError
from domain_finder.domain.models import DomainSearchParams, ProviderConfig
from domain_finder.domain.ports import DomainProviderPort
from domain_finder.infrastructure.http import HttpClient
from domain_finder.prompts.templates import build_prompt


class BaseLLMProvider(DomainProviderPort, ABC):
    """Base class for LLM providers."""

    def __init__(
        self,
        config: ProviderConfig,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        """
        Initialize base LLM provider.

        Args:
            config: Provider configuration
            http_client: Optional HTTP client (creates new one if not provided)
        """
        self.config = config
        self._http_client = http_client or HttpClient(
            timeout=config.timeout,
            retries=3,
        )

    def generate_domains(self, params: DomainSearchParams) -> str:
        """
        Generate domain suggestions using LLM.

        Args:
            params: Parameters for domain generation

        Returns:
            Raw text response from LLM containing domain suggestions

        Raises:
            ProviderError: If generation fails
        """
        prompt = build_prompt(
            topic=params.topic,
            tlds=params.tlds,
            count=params.count,
            language=params.language,
            min_len=params.min_len,
            max_len=params.max_len,
        )
        return self._generate_with_prompt(prompt)

    @abstractmethod
    def _generate_with_prompt(self, prompt: str) -> str:
        """
        Generate response from LLM using prompt.

        Args:
            prompt: Prompt text

        Returns:
            Raw text response from LLM

        Raises:
            ProviderError: If generation fails
        """
        pass

