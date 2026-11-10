"""Shared test helpers for backend unit tests."""
from __future__ import annotations

from backend.app.core.config import Settings, clear_settings_cache


def mock_settings(**overrides: object) -> Settings:
    clear_settings_cache()
    base = {
        "_env_file": None,
        "FREE_MODEL_ALLOWLIST": "mock/free-model,mock/free-fallback,meta/muse-spark-1.3-contributor",
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
        # Isolate from process env provider keys so offline tests stay deterministic.
        "GROQ_API_KEY": "",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "MISTRAL_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "META_API_KEY": "",
        "MODEL_API_KEY": "",
        "LLAMA_API_KEY": "",
        "META_LAST_RESORT_ENABLED": "false",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]
