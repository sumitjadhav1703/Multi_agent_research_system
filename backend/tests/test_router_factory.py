"""Router factory builds role aliases and free-only deployments."""
from __future__ import annotations

import unittest

from backend.app.providers.mock_router import MockRouter
from backend.app.providers.router_factory import (
    ROLE_ALIASES,
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


if __name__ == "__main__":
    unittest.main()
