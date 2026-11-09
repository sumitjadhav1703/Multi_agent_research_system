"""ModelClient success, failover, and failure-path tests."""
from __future__ import annotations

import unittest

from backend.app.providers.client import ModelClient
from backend.app.providers.errors import (
    AllProvidersUnavailable,
    InvalidRequestError,
    ProviderAuthError,
    ProviderRateLimitError,
    UnsupportedCapabilityError,
)
from backend.app.providers.mock_router import (
    MockAuthError,
    MockInvalidRequestError,
    MockRateLimitError,
    MockRouter,
    MockTimeoutError,
    always_fail,
    failing_then_fallback_success,
    malformed_output_behavior,
)
from backend.app.providers.router_factory import build_model_list_and_fallbacks
from backend.tests.helpers import mock_settings


class ModelClientTests(unittest.TestCase):
    def test_primary_success(self) -> None:
        settings = mock_settings()
        client = ModelClient(settings=settings)
        result = client.complete("planner", [{"role": "user", "content": "plan this"}])
        self.assertIn("mock:", result.content)
        self.assertEqual(result.role, "planner")
        self.assertEqual(result.alias, "rm-planner")
        self.assertFalse(result.usage.is_unknown)

    def test_primary_429_falls_back(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=failing_then_fallback_success({"rm-planner"}),
        )
        client = ModelClient(settings=settings, router=router)
        result = client.complete("planner", [{"role": "user", "content": "x"}])
        self.assertEqual(result.content, "ok:rm-planner-fallback")
        self.assertGreaterEqual(len(router.calls), 2)
        self.assertEqual(router.calls[0]["model"], "rm-planner")
        self.assertEqual(router.calls[1]["model"], "rm-planner-fallback")

    def test_both_deployments_429_stop_after_one_fallback(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(lambda: MockRateLimitError("limited", retry_after=12.5)),
        )
        client = ModelClient(settings=settings, router=router)
        with self.assertRaises(ProviderRateLimitError) as caught:
            client.complete("planner", [{"role": "user", "content": "x"}])
        self.assertEqual(caught.exception.retry_after, 12.5)
        self.assertEqual(caught.exception.error_class, "rate_limit")
        self.assertEqual([call["model"] for call in router.calls], ["rm-planner", "rm-planner-fallback"])

        judge = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(lambda: MockRateLimitError("judge limited", retry_after=3)),
        )
        judge_client = ModelClient(settings=settings, router=judge)
        with self.assertRaises(ProviderRateLimitError) as judge_caught:
            judge_client.complete("eval_judge", [{"role": "user", "content": "score"}])
        self.assertEqual(judge_caught.exception.retry_after, 3)
        self.assertEqual([call["model"] for call in judge.calls], ["rm-eval-judge"])

    def test_auth_and_invalid_request_do_not_fall_back(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        denied = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(MockAuthError),
        )
        client = ModelClient(settings=settings, router=denied)
        with self.assertRaises(ProviderAuthError):
            client.complete("researcher", [{"role": "user", "content": "x"}])
        self.assertEqual([call["model"] for call in denied.calls], ["rm-researcher"])

        invalid = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(MockInvalidRequestError),
        )
        invalid_client = ModelClient(settings=settings, router=invalid)
        with self.assertRaises(InvalidRequestError):
            invalid_client.complete("writer", [{"role": "user", "content": "x"}])
        self.assertEqual([call["model"] for call in invalid.calls], ["rm-writer"])

    def test_timeout_then_fallback(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)

        def behavior(model, messages, kwargs):
            if model == "rm-researcher" and not kwargs.get("_from_fallback"):
                raise MockTimeoutError("timeout")
            from backend.app.providers.mock_router import MockChoice, MockMessage, MockResponse, MockUsage

            return MockResponse(
                choices=[MockChoice(message=MockMessage(content="recovered"))],
                model=model,
                usage=MockUsage(1, 1, 2),
            )

        router = MockRouter(model_list=model_list, fallbacks=fallbacks, behavior=behavior)
        client = ModelClient(settings=settings, router=router)
        result = client.complete("researcher", [{"role": "user", "content": "q"}])
        self.assertEqual(result.content, "recovered")

    def test_malformed_output_raises(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=malformed_output_behavior(),
        )
        client = ModelClient(settings=settings, router=router)
        with self.assertRaises(UnsupportedCapabilityError):
            client.complete("writer", [{"role": "user", "content": "write"}])

    def test_all_providers_unavailable(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(lambda: MockRateLimitError("exhausted")),
        )
        client = ModelClient(settings=settings, router=router)
        with self.assertRaises(ProviderRateLimitError):
            client.complete("verifier", [{"role": "user", "content": "check"}])

    def test_auth_error_maps_cleanly(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(MockAuthError),
        )
        client = ModelClient(settings=settings, router=router)
        with self.assertRaises(ProviderAuthError):
            client.complete("writer", [{"role": "user", "content": "x"}])

    def test_tool_calling_kwargs_accepted_by_mock(self) -> None:
        settings = mock_settings()
        client = ModelClient(settings=settings)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            }
        ]
        result = client.complete(
            "researcher",
            [{"role": "user", "content": "search"}],
            tools=tools,
        )
        self.assertTrue(result.content)
        self.assertEqual(client.router.calls[-1]["kwargs"].get("tools"), tools)

    def test_structured_output_kwargs_accepted(self) -> None:
        settings = mock_settings()
        client = ModelClient(settings=settings)
        fmt = {"type": "json_object"}
        result = client.complete(
            "planner",
            [{"role": "user", "content": "json please"}],
            response_format=fmt,
        )
        self.assertTrue(result.content)
        self.assertEqual(client.router.calls[-1]["kwargs"].get("response_format"), fmt)

    def test_unknown_usage_stays_unknown_on_empty_usage(self) -> None:
        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)

        def behavior(model, messages, kwargs):
            from backend.app.providers.mock_router import MockChoice, MockMessage, MockResponse

            return MockResponse(
                choices=[MockChoice(message=MockMessage(content="hello"))],
                model=model,
                usage=None,
            )

        router = MockRouter(model_list=model_list, fallbacks=fallbacks, behavior=behavior)
        client = ModelClient(settings=settings, router=router)
        result = client.complete("eval_judge", [{"role": "user", "content": "score"}])
        self.assertTrue(result.usage.is_unknown)

    def test_timeout_exhaustion_uses_meta_last_resort(self) -> None:
        from backend.app.providers.mock_router import MockChoice, MockMessage, MockResponse, MockUsage

        settings = mock_settings(META_API_KEY="meta-test-key", META_LAST_RESORT_ENABLED="true")
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(MockTimeoutError),
        )
        calls: list[str] = []

        def last_resort(*, model, messages, api_key, **kwargs):
            del messages, kwargs
            calls.append(model)
            self.assertEqual(api_key, "meta-test-key")
            return MockResponse(
                choices=[MockChoice(message=MockMessage(content="rescued"))],
                model=model,
                usage=MockUsage(1, 1, 2),
            )

        client = ModelClient(settings=settings, router=router, last_resort_complete=last_resort)
        result = client.complete("planner", [{"role": "user", "content": "plan"}])
        self.assertEqual(result.content, "rescued")
        self.assertTrue(result.last_resort)
        self.assertEqual(result.model, "meta/muse-spark-1.3-contributor")
        self.assertEqual(calls, ["meta/muse-spark-1.3-contributor"])
        self.assertEqual(
            [call["model"] for call in router.calls],
            ["rm-planner", "rm-planner-fallback"],
        )

    def test_rate_limit_exhaustion_uses_meta_last_resort(self) -> None:
        from backend.app.providers.mock_router import MockChoice, MockMessage, MockResponse, MockUsage

        settings = mock_settings(META_API_KEY="meta-test-key", META_LAST_RESORT_ENABLED="true")
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(lambda: MockRateLimitError("down")),
        )

        def last_resort(*, model, messages, api_key, **kwargs):
            del messages, api_key, kwargs
            return MockResponse(
                choices=[MockChoice(message=MockMessage(content="meta-ok"))],
                model=model,
                usage=MockUsage(1, 1, 2),
            )

        client = ModelClient(settings=settings, router=router, last_resort_complete=last_resort)
        result = client.complete("writer", [{"role": "user", "content": "write"}])
        self.assertEqual(result.content, "meta-ok")
        self.assertTrue(result.last_resort)

    def test_last_resort_disabled_stays_unavailable(self) -> None:
        settings = mock_settings(META_API_KEY="meta-test-key", META_LAST_RESORT_ENABLED="false")
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(MockTimeoutError),
        )
        calls: list[str] = []

        def last_resort(*, model, messages, api_key, **kwargs):
            del messages, api_key, kwargs
            calls.append(model)
            raise AssertionError("last resort must not run when disabled")

        client = ModelClient(settings=settings, router=router, last_resort_complete=last_resort)
        with self.assertRaises(AllProvidersUnavailable):
            client.complete("planner", [{"role": "user", "content": "plan"}])
        self.assertEqual(calls, [])

    def test_invalid_request_does_not_call_meta_last_resort(self) -> None:
        settings = mock_settings(META_API_KEY="meta-test-key", META_LAST_RESORT_ENABLED="true")
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(MockInvalidRequestError),
        )
        calls: list[str] = []

        def last_resort(*, model, messages, api_key, **kwargs):
            del messages, api_key, kwargs
            calls.append(model)
            raise AssertionError("invalid requests must not burn Meta")

        client = ModelClient(settings=settings, router=router, last_resort_complete=last_resort)
        with self.assertRaises(InvalidRequestError):
            client.complete("writer", [{"role": "user", "content": "x"}])
        self.assertEqual(calls, [])

    def test_mock_provider_builtin_last_resort_without_injector(self) -> None:
        settings = mock_settings(META_API_KEY="meta-test-key", META_LAST_RESORT_ENABLED="true")
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=always_fail(MockTimeoutError),
        )
        client = ModelClient(settings=settings, router=router)
        result = client.complete("researcher", [{"role": "user", "content": "q"}])
        self.assertTrue(result.last_resort)
        self.assertIn("last-resort:", result.content)
        self.assertEqual(result.model, "meta/muse-spark-1.3-contributor")


if __name__ == "__main__":
    unittest.main()
