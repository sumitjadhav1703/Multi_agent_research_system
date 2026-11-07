"""Free-only configuration validation tests."""
from __future__ import annotations

import os
import unittest

from pydantic import ValidationError

from backend.app.core.config import Settings, clear_settings_cache
from backend.app.jobs.turnstile import OFFICIAL_TURNSTILE_VERIFY_URL


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()

    def tearDown(self) -> None:
        clear_settings_cache()

    def test_default_settings_validate(self) -> None:
        settings = Settings(
            _env_file=None,
            USE_MOCK_PROVIDER="true",
        )
        self.assertFalse(settings.allow_paid_models)
        self.assertIn("groq/openai/gpt-oss-20b", settings.allowlist)
        self.assertEqual(settings.role_models()["planner"][0], "groq/openai/gpt-oss-20b")

    def test_paid_model_marker_rejected(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            Settings(
                _env_file=None,
                FREE_MODEL_ALLOWLIST="openai/gpt-4o,groq/openai/gpt-oss-20b",
                PLANNER_PRIMARY_MODEL="openai/gpt-4o",
                PLANNER_FALLBACK_MODEL=None,
                RESEARCH_PRIMARY_MODEL="groq/openai/gpt-oss-20b",
                RESEARCH_FALLBACK_MODEL=None,
                VERIFIER_PRIMARY_MODEL="groq/openai/gpt-oss-20b",
                VERIFIER_FALLBACK_MODEL=None,
                WRITER_PRIMARY_MODEL="groq/openai/gpt-oss-20b",
                WRITER_FALLBACK_MODEL=None,
                EVAL_JUDGE_PRIMARY_MODEL="groq/openai/gpt-oss-20b",
                EVAL_JUDGE_FALLBACK_MODEL=None,
            )
        self.assertIn("paid marker", str(caught.exception).lower())

    def test_model_not_on_allowlist_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                FREE_MODEL_ALLOWLIST="mock/free-model",
                PLANNER_PRIMARY_MODEL="groq/openai/gpt-oss-20b",
                PLANNER_FALLBACK_MODEL=None,
                RESEARCH_PRIMARY_MODEL="mock/free-model",
                RESEARCH_FALLBACK_MODEL=None,
                VERIFIER_PRIMARY_MODEL="mock/free-model",
                VERIFIER_FALLBACK_MODEL=None,
                WRITER_PRIMARY_MODEL="mock/free-model",
                WRITER_FALLBACK_MODEL=None,
                EVAL_JUDGE_PRIMARY_MODEL="mock/free-model",
                EVAL_JUDGE_FALLBACK_MODEL=None,
            )

    def test_allow_paid_models_flag_fails_closed(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            Settings(_env_file=None, ALLOW_PAID_MODELS="true", USE_MOCK_PROVIDER="true")
        self.assertIn("ALLOW_PAID_MODELS", str(caught.exception))

    def test_role_aliases_are_config_only(self) -> None:
        settings = Settings(
            _env_file=None,
            FREE_MODEL_ALLOWLIST="mock/free-model,mock/free-fallback",
            PLANNER_PRIMARY_MODEL="mock/free-model",
            PLANNER_FALLBACK_MODEL="mock/free-fallback",
            RESEARCH_PRIMARY_MODEL="mock/free-model",
            RESEARCH_FALLBACK_MODEL=None,
            VERIFIER_PRIMARY_MODEL="mock/free-model",
            VERIFIER_FALLBACK_MODEL=None,
            WRITER_PRIMARY_MODEL="mock/free-model",
            WRITER_FALLBACK_MODEL=None,
            EVAL_JUDGE_PRIMARY_MODEL="mock/free-model",
            EVAL_JUDGE_FALLBACK_MODEL=None,
            USE_MOCK_PROVIDER="true",
        )
        self.assertEqual(settings.planner_primary_model, "mock/free-model")
        self.assertEqual(settings.planner_fallback_model, "mock/free-fallback")

    def test_worker_id_defaults_are_unique_per_settings_object(self) -> None:
        first = Settings(_env_file=None, USE_MOCK_PROVIDER="true", WORKER_ID="")
        second = Settings(_env_file=None, USE_MOCK_PROVIDER="true", WORKER_ID="")
        self.assertNotEqual(first.worker_id, second.worker_id)
        self.assertIn(f"-{os.getpid()}-", first.worker_id)
        self.assertLessEqual(len(first.worker_id), 80)
        pinned = Settings(_env_file=None, USE_MOCK_PROVIDER="true", WORKER_ID="worker-a")
        self.assertEqual(pinned.worker_id, "worker-a")

    def test_turnstile_verify_url_rejects_other_hosts(self) -> None:
        settings = Settings(_env_file=None, USE_MOCK_PROVIDER="true")
        self.assertEqual(settings.turnstile_verify_url, OFFICIAL_TURNSTILE_VERIFY_URL)
        explicit = Settings(
            _env_file=None,
            USE_MOCK_PROVIDER="true",
            TURNSTILE_VERIFY_URL="https://challenges.cloudflare.com:443/turnstile/v0/siteverify",
        )
        self.assertEqual(explicit.turnstile_verify_url, OFFICIAL_TURNSTILE_VERIFY_URL)
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                USE_MOCK_PROVIDER="true",
                TURNSTILE_VERIFY_URL="https://example.test/siteverify",
            )


if __name__ == "__main__":
    unittest.main()
