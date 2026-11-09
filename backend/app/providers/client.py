"""Internal model-client interface over LiteLLM Router role aliases."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

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
    MockChoice,
    MockInvalidRequestError,
    MockMessage,
    MockRateLimitError,
    MockResponse,
    MockTimeoutError,
    MockUsage,
)
from backend.app.providers.router_factory import alias_for_role, create_router
from backend.app.providers.usage import TokenUsage, extract_usage

LastResortComplete = Callable[..., Any]


@dataclass(frozen=True)
class ModelResponse:
    content: str
    role: RoleName
    alias: str
    model: str | None
    usage: TokenUsage
    raw: Any = None
    last_resort: bool = False


class ModelClient:
    """Role-based completion client. Model IDs live in Settings, not call sites."""

    def __init__(
        self,
        settings: Settings | None = None,
        router: Any | None = None,
        *,
        last_resort_complete: LastResortComplete | None = None,
    ):
        self.settings = settings or get_settings()
        self.router = router if router is not None else create_router(self.settings)
        self._last_resort_complete = last_resort_complete

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
                if self._should_try_last_resort(mapped):
                    try:
                        raw = self._invoke_last_resort(messages=messages, **kwargs)
                    except Exception as last_exc:  # noqa: BLE001
                        last_mapped = self._map_exception(last_exc)
                        span.set(
                            **{
                                "error.code": type(last_mapped).__name__,
                                "fallback_used": "last_resort_meta_failed",
                                "last_resort_model": self.settings.meta_last_resort_model,
                            }
                        )
                        raise last_mapped from last_exc
                    return self._build_response(
                        role=role,
                        alias=alias,
                        raw=raw,
                        primary=primary,
                        fallback=fallback,
                        span=span,
                        last_resort=True,
                    )
                span.set(**{"error.code": type(mapped).__name__})
                raise mapped from exc

            return self._build_response(
                role=role,
                alias=alias,
                raw=raw,
                primary=primary,
                fallback=fallback,
                span=span,
                last_resort=False,
            )

    def _build_response(
        self,
        *,
        role: RoleName,
        alias: str,
        raw: Any,
        primary: str,
        fallback: str | None,
        span: Any,
        last_resort: bool,
    ) -> ModelResponse:
        content = _extract_content(raw)
        usage = extract_usage(raw)
        model_name = getattr(raw, "model", None)
        if model_name is None and isinstance(raw, dict):
            model_name = raw.get("model")
        if last_resort:
            fallback_flag = "last_resort_meta"
            if not model_name:
                model_name = self.settings.meta_last_resort_model
        else:
            fallback_flag = _fallback_used(
                model_name, primary=primary, fallback=fallback, alias=alias
            )
        span.set(
            model=model_name or "unknown",
            fallback_used=fallback_flag,
            last_resort_model=self.settings.meta_last_resort_model if last_resort else "none",
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
            last_resort=last_resort,
        )

    def _should_try_last_resort(self, error: ModelClientError) -> bool:
        if not self.settings.meta_last_resort_active():
            return False
        # Do not burn Meta on clear client faults. Auth on the free chain also stays
        # fail-closed so a bad free key does not auto-spend Meta.
        if isinstance(error, (InvalidRequestError, ProviderAuthError, UnsupportedCapabilityError)):
            return False
        return isinstance(error, (AllProvidersUnavailable, ProviderRateLimitError))

    def _invoke_last_resort(self, *, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        model_id = self.settings.meta_last_resort_model
        api_key = self.settings.resolved_meta_api_key()
        call_kwargs = {
            "temperature": kwargs.get("temperature", 0.0),
            "num_retries": 0,
            "timeout": self.settings.litellm_request_timeout,
        }
        if "max_tokens" in kwargs and kwargs["max_tokens"] is not None:
            call_kwargs["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("tools") is not None:
            call_kwargs["tools"] = kwargs["tools"]
        if kwargs.get("response_format") is not None:
            call_kwargs["response_format"] = kwargs["response_format"]

        if self._last_resort_complete is not None:
            return self._last_resort_complete(
                model=model_id,
                messages=messages,
                api_key=api_key,
                **call_kwargs,
            )

        if self.settings.use_mock_provider:
            return MockResponse(
                choices=[
                    MockChoice(
                        message=MockMessage(content=f"last-resort:{model_id}:{messages[-1].get('content', '')}")
                    )
                ],
                model=model_id,
                usage=MockUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
                _hidden_params={"model_id": model_id, "last_resort": True},
            )

        from litellm import completion as litellm_completion

        return litellm_completion(
            model=model_id,
            messages=messages,
            api_key=api_key,
            **call_kwargs,
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
