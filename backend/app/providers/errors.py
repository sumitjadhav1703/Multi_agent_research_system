"""Normalized provider errors for the ResearchMind model client."""
from __future__ import annotations


class ModelClientError(Exception):
    """Base error for model client failures (safe for API surfaces)."""

    def __init__(self, message: str, *, error_class: str = "model_client_error"):
        super().__init__(message)
        self.error_class = error_class


class ProviderRateLimitError(ModelClientError):
    def __init__(self, message: str = "Provider rate limit reached.", *, retry_after: float | None = None):
        super().__init__(message, error_class="rate_limit")
        self.retry_after = retry_after


class ProviderAuthError(ModelClientError):
    def __init__(self, message: str = "Provider rejected credentials."):
        super().__init__(message, error_class="auth")


class UnsupportedCapabilityError(ModelClientError):
    def __init__(self, message: str = "Provider does not support the requested capability."):
        super().__init__(message, error_class="unsupported_capability")


class AllProvidersUnavailable(ModelClientError):
    def __init__(self, message: str = "All configured providers are unavailable."):
        super().__init__(message, error_class="all_providers_unavailable")


class InvalidRequestError(ModelClientError):
    def __init__(self, message: str = "Invalid model request."):
        super().__init__(message, error_class="invalid_request")
