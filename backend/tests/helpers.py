"""Shared test helpers for backend unit tests."""
from __future__ import annotations

from backend.app.core.config import Settings, clear_settings_cache


def mock_settings(**overrides: object) -> Settings:
    clear_settings_cache()
    base = {
        "_env_file": None,
        "FREE_MODEL_ALLOWLIST": "mock/free-model,mock/free-fallback",
        "PLANNER_PRIMARY_MODEL": "mock/free-model",
        "PLANNER_FALLBACK_MODEL": "mock/free-fallback",
        "RESEARCH_PRIMARY_MODEL": "mock/free-model",
        "RESEARCH_FALLBACK_MODEL": "mock/free-fallback",
        "VERIFIER_PRIMARY_MODEL": "mock/free-model",
        "VERIFIER_FALLBACK_MODEL": "mock/free-fallback",
        "WRITER_PRIMARY_MODEL": "mock/free-model",
        "WRITER_FALLBACK_MODEL": "mock/free-fallback",
        "EVAL_JUDGE_PRIMARY_MODEL": "mock/free-model",
        "EVAL_JUDGE_FALLBACK_MODEL": None,
        "USE_MOCK_PROVIDER": "true",
        "LITELLM_NUM_RETRIES": "0",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]
