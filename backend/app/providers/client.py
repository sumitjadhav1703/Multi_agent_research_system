"""Internal model-client interface over LiteLLM Router role aliases."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.observability import start_span

from backend.app.core.config import RoleName, Settings, get_settings
from backend.app.providers.errors import (
    AllProvidersUnavailable,
    InvalidRequestError,
    ModelClientError,
    ProviderAuthError,
    ProviderRateLimitError,
    UnsupportedCapabilityError,
)
from backend.app.providers.mock_router import (
    MockAuthError,
    MockInvalidRequestError,
    MockRateLimitError,
    MockTimeoutError,
)
from backend.app.providers.router_factory import alias_for_role, create_router
from backend.app.providers.usage import TokenUsage, extract_usage


@dataclass(frozen=True)
class ModelResponse:
    content: str
    role: RoleName
    alias: str
    model: str | None
    usage: TokenUsage
    raw: Any = None


class ModelClient:
    """Role-based completion client. Model IDs live in Settings, not call sites."""

    def __init__(self, settings: Settings | None = None, router: Any | None = None):
        self.settings = settings or get_settings()
        self.router = router if router is not None else create_router(self.settings)

    def complete(
        self,
        role: RoleName,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> ModelResponse:
        if role not in self.settings.role_models():
            raise InvalidRequestError(f"Unknown role '{role}'.")
        alias = alias_for_role(role)
        primary, fallback = self.settings.role_models()[role]
        kwargs: dict[str, Any] = {
            "temperature": temperature,
            "num_retries": self.settings.litellm_num_retries,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools is not None:
            kwargs["tools"] = tools
        if response_format is not None:
            kwargs["response_format"] = response_format

        with start_span(
            "provider.call",
            role=role,
            alias=alias,
            primary_model=primary,
            fallback_model=fallback or "none",
            retries_configured=self.settings.litellm_num_retries,
            retry_count="unknown",
            fallback_used="unknown",
            model="unknown",
            prompt_tokens="unknown",
            completion_tokens="unknown",
            total_tokens="unknown",
        ) as span:
            try:
                raw = self.router.completion(model=alias, messages=messages, **kwargs)
            except Exception as exc:  # noqa: BLE001 — normalized below
                mapped = self._map_exception(exc)
                span.set(**{"error.code": type(mapped).__name__})
                raise mapped from exc

            content = _extract_content(raw)
            usage = extract_usage(raw)
            model_name = getattr(raw, "model", None)
            if model_name is None and isinstance(raw, dict):
                model_name = raw.get("model")
            span.set(
                model=model_name or "unknown",
                fallback_used=_fallback_used(model_name, primary=primary, fallback=fallback, alias=alias),
                retry_count=_retry_count(raw),
                prompt_tokens=_token_value(usage.prompt_tokens),
                completion_tokens=_token_value(usage.completion_tokens),
                total_tokens=_token_value(usage.total_tokens),
            )
            if content is None:
                raise UnsupportedCapabilityError("Model returned empty or malformed content.")

        return ModelResponse(
            content=content,
            role=role,
            alias=alias,
            model=model_name,
            usage=usage,
            raw=raw,
        )

    def _map_exception(self, exc: Exception) -> ModelClientError:
        name = type(exc).__name__.lower()
        message = str(exc)
        status = getattr(exc, "status_code", None)

        if isinstance(exc, MockRateLimitError) or "ratelimit" in name or status == 429:
            retry_after = getattr(exc, "retry_after", None)
            return ProviderRateLimitError(retry_after=retry_after)
        if isinstance(exc, MockAuthError) or "auth" in name or status in {401, 403}:
            return ProviderAuthError()
        if isinstance(exc, MockInvalidRequestError) or "badrequest" in name or status == 400:
            return InvalidRequestError("Invalid request for configured model.")
        if isinstance(exc, MockTimeoutError) or "timeout" in name:
            return AllProvidersUnavailable("Provider timed out and no healthy fallback remained.")
        if "notfound" in name or "model" in name and "not" in message.lower():
            return AllProvidersUnavailable("Configured model is unavailable.")
        # When Router exhausted fallbacks it often surfaces the last error.
        return AllProvidersUnavailable("All configured providers failed for this role.")


def _token_value(value: int | None) -> int | str:
    """Keep a reported zero. Missing usage stays unknown instead of becoming zero."""
    if value is None:
        return "unknown"
    return value


def _fallback_used(model_name: str | None, *, primary: str, fallback: str | None, alias: str) -> str:
    if not isinstance(model_name, str) or not model_name:
        return "unknown"
    fallback_names = {f"{alias}-fallback"}
    if fallback:
        fallback_names.add(fallback)
    if model_name in fallback_names:
        return "true"
    if model_name in {primary, alias}:
        return "false"
    return "unknown"


def _retry_count(raw: Any) -> int | str:
    hidden = getattr(raw, "_hidden_params", None)
    if not isinstance(hidden, dict):
        return "unknown"
    for key in ("retry_count", "attempted_retries", "num_retries"):
        value = hidden.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return "unknown"


def _extract_content(raw: Any) -> str | None:
    try:
        choices = raw.choices if hasattr(raw, "choices") else raw.get("choices")
        if not choices:
            return None
        first = choices[0]
        message = first.message if hasattr(first, "message") else first.get("message")
        if message is None:
            return None
        content = message.content if hasattr(message, "content") else message.get("content")
        if content is None:
            return None
        text = str(content).strip()
        return text or None
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
