"""Base LLM provider implementation."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

from domain_finder.domain.models import DomainSearchParams, ProviderConfig
from domain_finder.domain.ports import DomainProviderPort
from domain_finder.infrastructure.http import HttpClient
from domain_finder.prompts.templates import build_prompt


class BaseLLMProvider(DomainProviderPort, ABC):
    """Base class for LLM providers with concurrency control."""

    # Global semaphore for limiting concurrent LLM requests across all instances
    _global_semaphore: threading.BoundedSemaphore | None = None
    _semaphore_lock = threading.Lock()

    def __init__(
        self,
        config: ProviderConfig,
        http_client: HttpClient | None = None,
        max_concurrent_requests: int = 8,
    ) -> None:
        """
        Initialize base LLM provider.

        Args:
            config: Provider configuration
            http_client: Optional HTTP client (creates new one if not provided)
            max_concurrent_requests: Maximum concurrent LLM requests (global limit)
        """
        self.config = config
        self._http_client = http_client or HttpClient(
            timeout=config.timeout,
            retries=3,
        )
        self._max_concurrent = max_concurrent_requests

        # Initialize global semaphore if not exists
        with BaseLLMProvider._semaphore_lock:
            if BaseLLMProvider._global_semaphore is None:
                BaseLLMProvider._global_semaphore = threading.BoundedSemaphore(
                    max_concurrent_requests
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
            min_len=params.min_len,
            max_len=params.max_len,
        )
        return self._generate_with_prompt(prompt)

    def generate_domains_stream(
        self,
        params: DomainSearchParams,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """
        Generate domain suggestions using LLM with streaming.

        Args:
            params: Parameters for domain generation
            on_chunk: Optional callback for each chunk (for real-time updates)

        Returns:
            Complete text response from LLM

        Raises:
            ProviderError: If generation fails
        """
        prompt = build_prompt(
            topic=params.topic,
            tlds=params.tlds,
            count=params.count,
            min_len=params.min_len,
            max_len=params.max_len,
        )
        return self._generate_with_prompt_stream(prompt, on_chunk)

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

    def _generate_with_prompt_stream(
        self,
        prompt: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """
        Generate response from LLM using prompt with streaming.

        Default implementation collects chunks and returns full text.
        Subclasses can override for provider-specific streaming.

        Args:
            prompt: Prompt text
            on_chunk: Optional callback for each chunk

        Returns:
            Complete text response from LLM

        Raises:
            ProviderError: If generation fails
        """
        # Default: fallback to non-streaming
        return self._generate_with_prompt(prompt)

    def _acquire_semaphore(self) -> None:
        """Acquire global semaphore for concurrent request limiting."""
        if BaseLLMProvider._global_semaphore:
            BaseLLMProvider._global_semaphore.acquire()

    def _release_semaphore(self) -> None:
        """Release global semaphore."""
        if BaseLLMProvider._global_semaphore:
            BaseLLMProvider._global_semaphore.release()
