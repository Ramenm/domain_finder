"""OpenAI-compatible LLM provider implementation."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

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
                "OPENAI_API_KEY не найден в переменных окружения. "
                "Установите его в файле .env или в переменных окружения."
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
        self._display_name = self._get_display_name(base_url)

    def _get_display_name(self, base_url: str) -> str:
        """
        Get display name for provider based on base URL.
        
        Args:
            base_url: Base URL of the API endpoint
            
        Returns:
            Display name for the provider
        """
        base_url_lower = base_url.lower()
        
        # Check for known providers by URL pattern
        if "api.openai.com" in base_url_lower:
            return "OpenAI"
        elif "openai" in base_url_lower:
            return "OpenAI (custom)"
        elif "anthropic" in base_url_lower or "claude" in base_url_lower:
            return "Anthropic"
        elif "google" in base_url_lower or "gemini" in base_url_lower:
            return "Google"
        elif "mistral" in base_url_lower:
            return "Mistral"
        elif "groq" in base_url_lower:
            return "Groq"
        elif "together" in base_url_lower:
            return "Together AI"
        elif "deepseek" in base_url_lower:
            return "DeepSeek"
        else:
            # Extract domain from URL for custom providers
            try:
                parsed = urlparse(base_url)
                domain = parsed.netloc or parsed.path.split("/")[0]
                if domain:
                    # Remove port if present
                    domain = domain.split(":")[0]
                    # Get main domain part
                    parts = domain.split(".")
                    if len(parts) >= 2:
                        main_domain = parts[-2]  # e.g., "example" from "api.example.com"
                        return main_domain.capitalize()
                    return domain.capitalize()
            except Exception:  # noqa: BLE001
                pass
            return "Custom Provider"

    @property
    def display_name(self) -> str:
        """Get display name for this provider."""
        return self._display_name

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
            raise ProviderError(f"Неожиданный формат ответа от OpenAI API: {e}; data={data!r}")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"Ошибка при обращении к OpenAI API: {e}")

