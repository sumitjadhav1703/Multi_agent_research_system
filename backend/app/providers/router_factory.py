"""Build a LiteLLM Router (or mock) from validated Settings."""
from __future__ import annotations

from typing import Any

from backend.app.core.config import RoleName, Settings
from backend.app.providers.mock_router import MockRouter


ROLE_ALIASES: dict[RoleName, str] = {
    "planner": "rm-planner",
    "researcher": "rm-researcher",
    "verifier": "rm-verifier",
    "writer": "rm-writer",
    "eval_judge": "rm-eval-judge",
}


def _deployment(alias: str, model_id: str, api_key: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model_id,
        "timeout": None,  # set on Router
        "max_retries": 0,  # LiteLLM owns retries; avoid SDK multiplication
    }
    if api_key:
        params["api_key"] = api_key
    return {"model_name": alias, "litellm_params": params}


def _api_key_for_model(settings: Settings, model_id: str) -> str | None:
    lowered = model_id.lower()
    if lowered.startswith("groq/"):
        return settings.groq_api_key
    if lowered.startswith("gemini/") or lowered.startswith("google/"):
        return settings.gemini_api_key or settings.google_api_key
    if lowered.startswith("mistral/"):
        return settings.mistral_api_key
    if lowered.startswith("openrouter/"):
        return settings.openrouter_api_key
    if lowered.startswith("meta_llama/"):
        return settings.llama_api_key
    if lowered.startswith("mock/"):
        return "mock-key"
    return None


def build_model_list_and_fallbacks(
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[dict[str, list[str]]]]:
    model_list: list[dict[str, Any]] = []
    fallbacks: list[dict[str, list[str]]] = []

    for role, alias in ROLE_ALIASES.items():
        primary, fallback = settings.role_models()[role]
        model_list.append(_deployment(alias, primary, _api_key_for_model(settings, primary)))
        if fallback:
            fallback_alias = f"{alias}-fallback"
            model_list.append(
                _deployment(fallback_alias, fallback, _api_key_for_model(settings, fallback))
            )
            fallbacks.append({alias: [fallback_alias]})
    return model_list, fallbacks


def create_router(settings: Settings, *, force_mock: bool | None = None) -> Any:
    """Create LiteLLM Router or MockRouter. Never enables paid deployments."""
    model_list, fallbacks = build_model_list_and_fallbacks(settings)
    use_mock = settings.use_mock_provider if force_mock is None else force_mock
    if use_mock:
        return MockRouter(model_list=model_list, fallbacks=fallbacks)

    from litellm import Router

    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=settings.litellm_num_retries,
        timeout=settings.litellm_request_timeout,
        set_verbose=False,
    )


def alias_for_role(role: RoleName) -> str:
    return ROLE_ALIASES[role]
