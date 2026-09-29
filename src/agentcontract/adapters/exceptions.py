"""Domain exceptions for external integration adapters."""


class AdapterError(Exception):
    """Base exception for all external adapter failures."""


class AdapterValidationError(AdapterError):
    """Raised when external tool calls, results, or payloads fail adapter validation."""


class AdapterConfigurationError(AdapterError):
    """Raised when an adapter configuration (e.g. API keys, URLs) is invalid or missing."""
