"""Normalize provider usage. Unknown usage must remain unknown, never zero."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None

    @property
    def is_unknown(self) -> bool:
        return (
            self.prompt_tokens is None
            and self.completion_tokens is None
            and self.total_tokens is None
        )


def extract_usage(response: Any) -> TokenUsage:
    """Pull usage from a LiteLLM/OpenAI-style response without inventing zeros."""
    usage = None
    if response is None:
        return TokenUsage(None, None, None)
    if hasattr(response, "usage"):
        usage = response.usage
    elif isinstance(response, dict):
        usage = response.get("usage")

    if usage is None:
        return TokenUsage(None, None, None)

    def _read(name: str) -> int | None:
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return TokenUsage(
        prompt_tokens=_read("prompt_tokens"),
        completion_tokens=_read("completion_tokens"),
        total_tokens=_read("total_tokens"),
    )
