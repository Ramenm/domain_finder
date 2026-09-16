"""OpenAI-compatible LLM provider implementation."""

from __future__ import annotations

from collections.abc import Callable
from ipaddress import ip_address
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
        config: ProviderConfig | None = None,
        settings: Settings | None = None,
        http_client: HttpClient | None = None,
        max_concurrent_requests: int | None = None,
    ) -> None:
        """
        Initialize OpenAI-compatible provider.

        Args:
            config: Provider configuration (uses defaults if not provided)
            settings: Application settings (for API key and base URL)
            http_client: Optional HTTP client
            max_concurrent_requests: Maximum concurrent LLM requests (uses settings default if not provided)

        Raises:
            ProviderError: If API key is missing
        """
        if settings is None:
            settings = Settings()

        api_key = settings.get_api_key("openai")
        if not api_key:
            raise ProviderError(
                "OPENAI_API_KEY not found in environment variables. "
                "Set it in .env file or environment variables."
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

        if http_client is None:
            http_client = HttpClient(
                timeout=config.timeout,
                retries=settings.max_retries,
                backoff_min=settings.retry_backoff_min,
                backoff_max=settings.retry_backoff_max,
                max_connections=settings.max_connections,
                max_keepalive_connections=settings.max_keepalive_connections,
            )
        max_concurrent = max_concurrent_requests or settings.max_concurrent_llm_requests
        super().__init__(config, http_client, max_concurrent_requests=max_concurrent)
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
                domain = parsed.hostname or parsed.path.split("/")[0]
                if domain:
                    try:
                        ip_address(domain)
                    except ValueError:
                        pass
                    else:
                        return domain
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
            # Acquire semaphore to limit concurrent requests
            self._acquire_semaphore()
            try:
                data = self._http_client.post(self.url, headers, payload)
                return data["choices"][0]["message"]["content"]  # type: ignore[no-any-return]
            finally:
                self._release_semaphore()
        except KeyError as e:
            raise ProviderError(
                f"Unexpected response format from OpenAI API: {e}; data={data!r}"
            ) from e
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"Error calling OpenAI API: {e}") from e

    def _generate_with_prompt_stream(
        self,
        prompt: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """
        Generate response from OpenAI-compatible API with streaming.

        Args:
            prompt: Prompt text
            on_chunk: Optional callback for each chunk

        Returns:
            Complete text response from LLM

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
            # Acquire semaphore to limit concurrent requests
            self._acquire_semaphore()
            try:
                parts = []
                for chunk in self._http_client.post_stream(self.url, headers, payload):
                    # OpenAI-compatible format: {"choices": [{"delta": {"content": "..."}}]}
                    try:
                        choice = chunk.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            parts.append(content)
                            if on_chunk:
                                on_chunk(content)
                    except (KeyError, IndexError):
                        # Skip malformed chunks
                        continue

                return "".join(parts)
            finally:
                self._release_semaphore()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"Error streaming from OpenAI API: {e}") from e
