"""Bounded role completions. JSON is parsed in-process; provider JSON mode is not required."""
from __future__ import annotations

import json
from typing import Any

from backend.app.graph.parsing import parse_json_object
from backend.app.graph.state import empty_usage
from backend.app.cost_estimate import refresh_estimated_cost
from backend.app.providers.errors import ModelClientError

RoleName = str


def complete_json(
    client: Any,
    usage: dict[str, Any] | None,
    *,
    role: RoleName,
    messages: list[dict[str, str]],
    max_tokens: int,
    max_model_calls: int,
) -> tuple[dict | None, dict[str, Any], str | None]:
    current = dict(usage or empty_usage())
    if int(current.get("llm_calls") or 0) >= max_model_calls:
        current["estimated_cost_usd"] = None
        return None, current, "model_budget"
    try:
        response = client.complete(
            role,
            messages,
            max_tokens=max_tokens,
            temperature=0,
        )
    except ModelClientError as exc:
        return None, record_usage(current, None), exc.error_class
    updated = record_usage(current, response)
    try:
        return parse_json_object(response.content), updated, None
    except (ValueError, json.JSONDecodeError):
        return None, updated, "invalid_output"


def record_usage(usage: dict[str, Any], response: Any) -> dict[str, Any]:
    """Count the call. Unknown token totals stay unknown instead of becoming zero."""
    updated = dict(usage)
    updated["llm_calls"] = int(updated.get("llm_calls") or 0) + 1
    token_usage = getattr(response, "usage", None)
    if response is None or token_usage is None or getattr(token_usage, "is_unknown", True):
        updated["token_usage_complete"] = False
        return refresh_estimated_cost(updated)
    if updated.get("token_usage_complete") is False:
        return refresh_estimated_cost(updated)
    prompt = token_usage.prompt_tokens
    completion = token_usage.completion_tokens
    total = token_usage.total_tokens
    if prompt is None or completion is None or total is None:
        updated["token_usage_complete"] = False
        return refresh_estimated_cost(updated)
    updated["prompt_tokens"] = int(updated.get("prompt_tokens") or 0) + prompt
    updated["completion_tokens"] = int(updated.get("completion_tokens") or 0) + completion
    updated["total_tokens"] = int(updated.get("total_tokens") or 0) + total
    updated["token_usage_complete"] = True
    return refresh_estimated_cost(updated)
