"""Deterministic mock router for CI — never calls real providers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class MockRateLimitError(Exception):
    def __init__(self, message: str = "mock 429", retry_after: float | None = 1.0):
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = 429


class MockTimeoutError(Exception):
    pass


class MockAuthError(Exception):
    pass


class MockInvalidRequestError(Exception):
    pass


@dataclass
class MockMessage:
    content: str
    tool_calls: list[Any] | None = None


@dataclass
class MockChoice:
    message: MockMessage
    finish_reason: str = "stop"


@dataclass
class MockUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class MockResponse:
    choices: list[MockChoice]
    model: str
    usage: MockUsage | None = None
    _hidden_params: dict[str, Any] = field(default_factory=dict)


Behavior = Callable[[str, list[dict[str, Any]], dict[str, Any]], MockResponse]


class MockRouter:
    """LiteLLM Router–compatible subset used by ModelClient in tests."""

    def __init__(
        self,
        *,
        behavior: Behavior | None = None,
        model_list: list[dict[str, Any]] | None = None,
        fallbacks: list[dict[str, list[str]]] | None = None,
    ):
        self.model_list = model_list or []
        self.fallbacks = fallbacks or []
        self.calls: list[dict[str, Any]] = []
        self._behavior = behavior or self._default_behavior
        self._alias_to_deployment: dict[str, str] = {}
        for entry in self.model_list:
            name = entry.get("model_name")
            params = entry.get("litellm_params") or {}
            if name and params.get("model"):
                self._alias_to_deployment[name] = params["model"]

    def _default_behavior(
        self, model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> MockResponse:
        last = messages[-1]["content"] if messages else ""
        return MockResponse(
            choices=[MockChoice(message=MockMessage(content=f"mock:{model}:{last}"))],
            model=self._alias_to_deployment.get(model, model),
            usage=MockUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            _hidden_params={"model_id": model},
        )

    def _fallback_for(self, model: str) -> str | None:
        for mapping in self.fallbacks:
            if model in mapping and mapping[model]:
                return mapping[model][0]
        return None

    def completion(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> MockResponse:
        self.calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        try:
            return self._behavior(model, messages, kwargs)
        except MockRateLimitError:
            fallback = self._fallback_for(model)
            if fallback and kwargs.get("_fallback_depth", 0) < 1:
                return self.completion(
                    fallback, messages, **{**kwargs, "_fallback_depth": 1, "_from_fallback": True}
                )
            raise
        except MockTimeoutError:
            fallback = self._fallback_for(model)
            if fallback and kwargs.get("_fallback_depth", 0) < 1:
                return self.completion(
                    fallback, messages, **{**kwargs, "_fallback_depth": 1, "_from_fallback": True}
                )
            raise

    async def acompletion(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> MockResponse:
        return self.completion(model, messages, **kwargs)


def failing_then_fallback_success(fail_models: set[str]) -> Behavior:
    def _behavior(model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> MockResponse:
        if model in fail_models and not kwargs.get("_from_fallback"):
            raise MockRateLimitError("primary 429")
        return MockResponse(
            choices=[MockChoice(message=MockMessage(content=f"ok:{model}"))],
            model=model,
            usage=MockUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )

    return _behavior


def always_fail(exc_factory: Callable[[], Exception] | None = None) -> Behavior:
    factory = exc_factory or (lambda: MockRateLimitError("down"))

    def _behavior(model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> MockResponse:
        raise factory()

    return _behavior


def malformed_output_behavior() -> Behavior:
    def _behavior(model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> MockResponse:
        return MockResponse(choices=[], model=model, usage=None)

    return _behavior
