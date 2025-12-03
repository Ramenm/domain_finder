"""Domain-specific exceptions."""


class DomainError(Exception):
    """Base exception for domain errors."""

    pass


class ProviderError(DomainError):
    """Error related to LLM provider operations."""

    pass


class DomainCheckError(DomainError):
    """Error related to domain availability checking."""

    pass


class ConfigurationError(DomainError):
    """Error related to configuration issues."""

    pass


class ValidationError(DomainError):
    """Error related to data validation."""

    pass
