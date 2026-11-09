"""Router factory builds role aliases and free-only deployments."""
from __future__ import annotations

import unittest

from backend.app.providers.mock_router import MockRouter
from backend.app.providers.router_factory import (
    ROLE_ALIASES,
    _api_key_for_model,
    build_model_list_and_fallbacks,
    create_router,
)
from backend.tests.helpers import mock_settings


class RouterFactoryTests(unittest.TestCase):
    def test_aliases_cover_all_roles(self) -> None:
        self.assertEqual(
            set(ROLE_ALIASES),
            {"planner", "researcher", "verifier", "writer", "eval_judge"},
        )

    def test_model_list_contains_only_allowlisted_deployments(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        models = [entry["litellm_params"]["model"] for entry in model_list]
        for model_id in models:
            self.assertIn(model_id, settings.allowlist)
        self.assertTrue(any("rm-planner" in mapping for mapping in fallbacks))

    def test_each_configured_fallback_is_one_hop(self) -> None:
        settings = mock_settings()
        _model_list, fallbacks = build_model_list_and_fallbacks(settings)
        seen: set[str] = set()
        for mapping in fallbacks:
            self.assertEqual(len(mapping), 1)
            alias, targets = next(iter(mapping.items()))
            self.assertEqual(targets, [f"{alias}-fallback"])
            seen.add(alias)
        self.assertEqual(seen, {"rm-planner", "rm-researcher", "rm-verifier", "rm-writer"})
        self.assertNotIn("rm-eval-judge", seen)

    def test_create_router_returns_mock_when_configured(self) -> None:
        settings = mock_settings()
        router = create_router(settings)
        self.assertIsInstance(router, MockRouter)

    def test_meta_llama_prefix_maps_to_llama_api_key_without_allowlisting(self) -> None:
        settings = mock_settings()
        self.assertIsNone(_api_key_for_model(settings, "meta_llama/Llama-3.3-8B-Instruct"))
        keyed = mock_settings(LLAMA_API_KEY="llama-test-key")
        self.assertEqual(
            _api_key_for_model(keyed, "meta_llama/Llama-3.3-8B-Instruct"),
            "llama-test-key",
        )
        self.assertNotIn("meta_llama/Llama-3.3-8B-Instruct", keyed.allowlist)

    def test_meta_muse_prefix_maps_to_resolved_meta_api_key(self) -> None:
        settings = mock_settings(META_API_KEY="meta-primary", META_LAST_RESORT_ENABLED="true")
        self.assertEqual(
            _api_key_for_model(settings, "meta/muse-spark-1.3-contributor"),
            "meta-primary",
        )
        aliased = mock_settings(
            META_API_KEY="",
            MODEL_API_KEY="model-alias-key",
            LLAMA_API_KEY="",
            META_LAST_RESORT_ENABLED="true",
        )
        self.assertEqual(
            _api_key_for_model(aliased, "meta/muse-spark-1.3-contributor"),
            "model-alias-key",
        )
        self.assertNotIn("meta/muse-spark-1.3-contributor", settings.allowlist)
        self.assertTrue(settings.meta_last_resort_active())
        self.assertEqual(settings.meta_last_resort_model, "meta/muse-spark-1.3-contributor")


if __name__ == "__main__":
    unittest.main()
