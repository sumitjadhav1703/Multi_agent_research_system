"""List-price usage estimate: tokens × USD-per-1M + search call rate.

Industry-standard formula used by OpenAI/Google/LiteLLM-style dashboards.
Free-tier runs still get a would-be list-price figure so the UI is not blank.
This is not an invoice and not provider-billed spend.
"""
from __future__ import annotations

# Approximate blended list rates (USD per 1M tokens), one figure for every routed model
# (default chain: Groq gpt-oss, OpenRouter/NVIDIA free fallbacks). Not per-model pricing.
INPUT_USD_PER_MTOK = 0.10
OUTPUT_USD_PER_MTOK = 0.40
# Order-of-magnitude Tavily-class list rate (USD per search call). Failed searches are
# counted too (the worker records search_calls=1 even when the search errors).
SEARCH_USD_PER_CALL = 0.005


def estimate_usage_cost_usd(
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    search_calls: int | None = None,
) -> str | None:
    """Return a 6-decimal USD string, or None when nothing measurable exists."""
    cost = 0.0
    measured = False
    if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool):
        cost += (prompt_tokens / 1_000_000) * INPUT_USD_PER_MTOK
        measured = True
    if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool):
        cost += (completion_tokens / 1_000_000) * OUTPUT_USD_PER_MTOK
        measured = True
    if isinstance(search_calls, int) and not isinstance(search_calls, bool) and search_calls > 0:
        cost += search_calls * SEARCH_USD_PER_CALL
        measured = True
    if not measured:
        return None
    return f"{cost:.6f}"


def refresh_estimated_cost(usage: dict) -> dict:
    """Set estimated_cost_usd from current token/search counters on the usage dict."""
    updated = dict(usage)
    updated["estimated_cost_usd"] = estimate_usage_cost_usd(
        prompt_tokens=updated.get("prompt_tokens") if isinstance(updated.get("prompt_tokens"), int) else None,
        completion_tokens=(
            updated.get("completion_tokens") if isinstance(updated.get("completion_tokens"), int) else None
        ),
        search_calls=updated.get("search_calls") if isinstance(updated.get("search_calls"), int) else None,
    )
    return updated
