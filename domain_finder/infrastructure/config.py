"""Configuration management using pydantic-settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Provider API Keys
    api_key_openai: str | None = Field(default=None, alias="OPENAI_API_KEY")

    # Domain checking preferences
    use_rdap: bool = Field(default=True, alias="USE_RDAP")
    registry_profile_file: str = Field(
        default=".domain_finder_registry_profiles.sqlite3",
        alias="REGISTRY_PROFILE_FILE",
    )

    # Default LLM settings
    default_provider: str = Field(default="openai", alias="DEFAULT_PROVIDER")
    default_model_openai: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
    )

    # HTTP settings
    http_timeout: float = Field(default=60.0, alias="HTTP_TIMEOUT")
    rdap_timeout: float = Field(default=10.0, alias="RDAP_TIMEOUT")
    max_connections: int = Field(default=100, alias="MAX_CONNECTIONS")
    max_keepalive_connections: int = Field(default=20, alias="MAX_KEEPALIVE_CONNECTIONS")

    # Retry settings
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_backoff_min: float = Field(default=1.0, alias="RETRY_BACKOFF_MIN")
    retry_backoff_max: float = Field(default=3.0, alias="RETRY_BACKOFF_MAX")

    # LLM concurrency settings
    max_concurrent_llm_requests: int = Field(default=8, alias="MAX_CONCURRENT_LLM_REQUESTS")
    enable_streaming: bool = Field(default=False, alias="ENABLE_STREAMING")

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for the specified provider."""
        provider_lower = provider.lower().strip()
        if provider_lower == "openai":
            return self.api_key_openai
        return None

    def get_default_model(self, provider: str) -> str:
        """Get default model for the specified provider."""
        provider_lower = provider.lower().strip()
        if provider_lower == "openai":
            return self.default_model_openai
        return self.default_model_openai

    def get_openai_base_url(self) -> str:
        """Get OpenAI base URL (supports custom endpoints)."""
        return self.openai_base_url
