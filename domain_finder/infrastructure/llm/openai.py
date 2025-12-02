"""OpenAI-compatible LLM provider implementation."""

from __future__ import annotations

from typing import Optional

from domain_finder.domain.errors import ProviderError
from domain_finder.domain.models import ProviderConfig
from domain_finder.infrastructure.config import Settings
from domain_finder.infrastructure.http import HttpClient
from domain_finder.infrastructure.llm.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """Universal OpenAI-compatible LLM provider."""

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        settings: Optional[Settings] = None,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        """
        Initialize OpenAI-compatible provider.

        Args:
            config: Provider configuration (uses defaults if not provided)
            settings: Application settings (for API key and base URL)
            http_client: Optional HTTP client

        Raises:
            ProviderError: If API key is missing
        """
        if settings is None:
            settings = Settings()

        api_key = settings.get_api_key("openai")
        if not api_key:
            raise ProviderError(
                "OPENAI_API_KEY not found in environment. "
                "Please set it in .env file or environment variables."
            )

        if config is None:
            model = settings.get_default_model("openai")
            config = ProviderConfig(
                provider="openai",
                model=model,
                temperature=0.7,
                timeout=60.0,
                api_key=api_key,
            )
        else:
            # Override API key from settings if not in config
            if not config.api_key:
                config.api_key = api_key

        super().__init__(config, http_client)
        base_url = settings.get_openai_base_url()
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/chat/completions"

    def _generate_with_prompt(self, prompt: str) -> str:
        """
        Generate response from OpenAI-compatible API.

        Args:
            prompt: Prompt text

        Returns:
            Raw text response from LLM

        Raises:
            ProviderError: If generation fails
        """
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
        }

        try:
            data = self._http_client.post(self.url, headers, payload)
            return data["choices"][0]["message"]["content"]
        except KeyError as e:
            raise ProviderError(f"Unexpected OpenAI response format: {e}; data={data!r}")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"OpenAI API error: {e}")

