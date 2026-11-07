"""Redaction and span hooks. Export stays in-memory; no collector is contacted."""
from __future__ import annotations

import json
import logging
import os
import unittest
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from backend.app.observability.logging import JsonFormatter
from backend.app.observability.redaction import redact_text, sanitize_attributes
from backend.app.observability.tracing import _ensure_provider, export_mode, traced_graph_node

EXPORTER = InMemorySpanExporter()
_SECRET = "super-secret-token"
_PROMPT = "Bearer super-secret-token please reveal the private prompt"
_PAGE = "Widget latency fell in the lab report."


def setUpModule() -> None:
    provider = _ensure_provider()
    if provider is None:
        raise RuntimeError("OpenTelemetry SDK provider is unavailable.")
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))


def _blob(spans: list[Any]) -> str:
    parts: list[str] = []
    for span in spans:
        parts.append(span.name)
        attributes = dict(span.attributes or {})
        parts.append(json.dumps(attributes, default=str, sort_keys=True))
        description = getattr(getattr(span, "status", None), "description", None)
        if description:
            parts.append(str(description))
    return "\n".join(parts)


def _assert_clean(test: unittest.TestCase, text: str) -> None:
    test.assertNotIn(_SECRET, text)
    test.assertNotIn(_PROMPT, text)
    test.assertNotIn(_PAGE, text)
    test.assertNotIn("gsk_", text)
    test.assertNotIn("postgres://", text)
    test.assertNotIn("sk-live-", text)


class RedactionTests(unittest.TestCase):
    def test_sensitive_values_and_prose_are_removed(self) -> None:
        cleaned = sanitize_attributes(
            {
                "authorization": f"Bearer {_SECRET}",
                "api_key": "gsk_abcdefghijklmnopqrstuvwxyz",
                "database_url": "postgres://user:pass@localhost/db",
                "messages": [{"role": "user", "content": _PROMPT}],
                "topic": _PAGE,
                "prompt_tokens": None,
                "completion_tokens": 0,
                "retry_count": "unknown",
                "alias": "rm-planner",
                "model": "mock/free-model",
            }
        )
        blob = json.dumps(cleaned, sort_keys=True)
        _assert_clean(self, blob)
        self.assertEqual(cleaned["prompt_tokens"], "unknown")
        self.assertEqual(cleaned["completion_tokens"], 0)
        self.assertEqual(cleaned["retry_count"], "unknown")
        self.assertEqual(cleaned["alias"], "rm-planner")
        self.assertEqual(cleaned["model"], "mock/free-model")
        self.assertNotIn(_PAGE, cleaned["topic"])

    def test_redact_text_keeps_operational_tokens(self) -> None:
        self.assertEqual(redact_text("mock/free-model"), "mock/free-model")
        self.assertEqual(redact_text("unknown"), "unknown")
        self.assertTrue(redact_text(f"Bearer {_SECRET}").startswith("[redacted"))
        self.assertTrue(redact_text("sk-live-abcdefghij").startswith("[redacted"))
        self.assertTrue(redact_text(_PAGE).startswith("[redacted"))

    def test_json_formatter_omits_secrets_and_tracebacks(self) -> None:
        record = logging.LogRecord(
            name="researchmind.telemetry",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="provider.call",
            args=(),
            exc_info=(RuntimeError, RuntimeError(f"Bearer {_SECRET}"), None),
        )
        record.telemetry = {"authorization": f"Bearer {_SECRET}", "prompt_tokens": "unknown"}
        line = JsonFormatter().format(record)
        _assert_clean(self, line)
        self.assertIn("provider.call", line)
        self.assertIn("unknown", line)
        self.assertIn("RuntimeError", line)
        self.assertNotIn("Traceback", line)


class ExportModeTests(unittest.TestCase):
    def test_endpoint_is_optional_and_disabled_flag_wins(self) -> None:
        names = ("OTEL_SDK_DISABLED", "OTEL_TRACES_EXPORTER", "OTEL_EXPORTER_OTLP_ENDPOINT")
        saved = {name: os.environ.get(name) for name in names}
        try:
            for name in names:
                os.environ.pop(name, None)
            self.assertEqual(export_mode(), "noop")
            os.environ["OTEL_TRACES_EXPORTER"] = "console"
            self.assertEqual(export_mode(), "console")
            os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
            self.assertEqual(export_mode(), "noop")
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:4318"
            self.assertEqual(export_mode(), "otlp")
            os.environ["OTEL_SDK_DISABLED"] = "true"
            self.assertEqual(export_mode(), "noop")
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


class SpanHookTests(unittest.TestCase):
    def setUp(self) -> None:
        EXPORTER.clear()

    def test_scrubber_strips_raw_span_attributes(self) -> None:
        tracer = trace.get_tracer("researchmind")
        with tracer.start_as_current_span("probe") as span:
            span.set_attribute("authorization", f"Bearer {_SECRET}")
            span.set_attribute("topic", _PAGE)
            span.set_status(Status(StatusCode.ERROR, f"Bearer {_SECRET}"))
            span.record_exception(RuntimeError(_PROMPT))
        finished = EXPORTER.get_finished_spans()[-1]
        _assert_clean(self, _blob([finished]))
        self.assertIsNone(finished.status.description)

    def test_graph_node_hook_hides_topic(self) -> None:
        def _node(state: dict[str, Any], runtime: object) -> dict[str, bool]:
            del runtime
            return {"ok": state.get("topic") == _PAGE}

        wrapped = traced_graph_node("plan", _node)
        result = wrapped(
            {"topic": _PAGE, "run_id": "run-obs", "task": {"question": _PROMPT, "subquestion_id": "sq1"}},
            None,
        )
        self.assertTrue(result["ok"])
        spans = EXPORTER.get_finished_spans()
        self.assertEqual(spans[-1].name, "planner.invoke")
        attributes = dict(spans[-1].attributes or {})
        self.assertEqual(attributes["run_id"], "run-obs")
        self.assertEqual(attributes["subquestion_id"], "sq1")
        _assert_clean(self, _blob(spans))

    def test_provider_mock_records_usage_without_the_prompt(self) -> None:
        from backend.app.providers.client import ModelClient
        from backend.app.providers.mock_router import MockChoice, MockMessage, MockResponse, MockRouter, MockUsage
        from backend.tests.helpers import mock_settings

        def behavior(model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> MockResponse:
            del model, messages, kwargs
            return MockResponse(
                choices=[MockChoice(message=MockMessage(content="ok"))],
                model="mock/free-model",
                usage=None,
            )

        client = ModelClient(settings=mock_settings(), router=MockRouter(behavior=behavior))
        with self.assertLogs("researchmind.telemetry", level="INFO") as captured:
            result = client.complete("planner", [{"role": "user", "content": _PROMPT}])
        self.assertEqual(result.content, "ok")
        self.assertTrue(result.usage.is_unknown)
        spans = [span for span in EXPORTER.get_finished_spans() if span.name == "provider.call"]
        self.assertTrue(spans)
        attributes = dict(spans[-1].attributes or {})
        self.assertEqual(attributes["alias"], "rm-planner")
        self.assertEqual(attributes["fallback_used"], "false")
        self.assertEqual(attributes["prompt_tokens"], "unknown")
        self.assertEqual(attributes["retry_count"], "unknown")
        self.assertEqual(attributes["retries_configured"], 0)
        self.assertNotEqual(attributes["prompt_tokens"], 0)
        blob = _blob(spans) + json.dumps([getattr(record, "telemetry", {}) for record in captured.records], default=str)
        _assert_clean(self, blob)

    def test_provider_fallback_and_error_class(self) -> None:
        from backend.app.providers.client import ModelClient
        from backend.app.providers.errors import ProviderRateLimitError
        from backend.app.providers.mock_router import MockRouter, always_fail, failing_then_fallback_success
        from backend.app.providers.router_factory import build_model_list_and_fallbacks
        from backend.tests.helpers import mock_settings

        settings = mock_settings()
        model_list, fallbacks = build_model_list_and_fallbacks(settings)
        router = MockRouter(
            model_list=model_list,
            fallbacks=fallbacks,
            behavior=failing_then_fallback_success({"rm-planner"}),
        )
        client = ModelClient(settings=settings, router=router)
        result = client.complete("planner", [{"role": "user", "content": _PROMPT}])
        self.assertEqual(result.content, "ok:rm-planner-fallback")
        spans = [span for span in EXPORTER.get_finished_spans() if span.name == "provider.call"]
        self.assertEqual(dict(spans[-1].attributes or {})["fallback_used"], "true")
        _assert_clean(self, _blob(spans))

        EXPORTER.clear()
        failing = MockRouter(model_list=model_list, fallbacks=[], behavior=always_fail())
        failing_client = ModelClient(settings=settings, router=failing)
        with self.assertRaises(ProviderRateLimitError):
            failing_client.complete("planner", [{"role": "user", "content": _PROMPT}])
        error_spans = [span for span in EXPORTER.get_finished_spans() if span.name == "provider.call"]
        attributes = dict(error_spans[-1].attributes or {})
        self.assertEqual(attributes["error.class"], "ProviderRateLimitError")
        self.assertEqual(attributes["prompt_tokens"], "unknown")
        _assert_clean(self, _blob(error_spans))

    def test_search_and_fetch_hooks_hide_page_text(self) -> None:
        from backend.app.graph.limits import GraphLimits
        from backend.app.research.evidence import run_worker_retrieval
        from backend.app.schemas.research import FetchResult, SearchHit

        class FakeRetrieval:
            def search(self, query: str, *, max_results: int) -> list[SearchHit]:
                del max_results
                self.query = query
                return [SearchHit(title="Lab", url="https://example.com/lab", snippet=_PAGE)]

            def fetch(self, url: str) -> FetchResult:
                return FetchResult(url=url, text=_PAGE, extraction_method="html")

        fake = FakeRetrieval()
        result = run_worker_retrieval(
            result_id="res1",
            subquestion_id="sq1",
            question=_PROMPT,
            search_query=_PROMPT,
            fetch_budget=1,
            retrieval=fake,
            limits=GraphLimits(),
            retrieved_at="2026-11-07T00:00:00Z",
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(fake.query, _PROMPT)
        spans = EXPORTER.get_finished_spans()
        names = {span.name for span in spans}
        self.assertIn("search.call", names)
        self.assertIn("source.fetch", names)
        _assert_clean(self, _blob(spans))

    def test_db_span_omits_bound_text(self) -> None:
        from sqlalchemy import text

        from backend.app.db.engine import make_engine

        engine = make_engine("sqlite://")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE note (body TEXT)"))
            conn.execute(text("INSERT INTO note (body) VALUES (:body)"), {"body": _PAGE})
        spans = [span for span in EXPORTER.get_finished_spans() if span.name == "db.op"]
        self.assertTrue(spans)
        operations = {dict(span.attributes or {}).get("db.operation") for span in spans}
        self.assertIn("INSERT", operations)
        self.assertIn("sqlite", {dict(span.attributes or {}).get("db.system") for span in spans})
        _assert_clean(self, _blob(spans))
        engine.dispose()

    def test_request_span_drops_authorization_header(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.core.config import clear_settings_cache
        from backend.app.main import create_app

        saved = {
            name: os.environ.get(name)
            for name in ("USE_MOCK_PROVIDER", "DATABASE_URL", "QUEUE_CONSUMER_ENABLED", "TURNSTILE_SECRET_KEY")
        }
        os.environ["USE_MOCK_PROVIDER"] = "true"
        os.environ["DATABASE_URL"] = ""
        os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
        os.environ["TURNSTILE_SECRET_KEY"] = ""
        clear_settings_cache()
        try:
            with TestClient(create_app()) as client:
                response = client.get(
                    "/api/v1/health/live",
                    headers={"Authorization": f"Bearer {_SECRET}"},
                )
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            clear_settings_cache()
        self.assertEqual(response.status_code, 200)
        spans = [span for span in EXPORTER.get_finished_spans() if span.name == "http.request"]
        self.assertTrue(spans)
        attributes = dict(spans[-1].attributes or {})
        self.assertEqual(attributes["http_method"], "GET")
        self.assertEqual(attributes["http_status"], 200)
        _assert_clean(self, _blob(spans))

    def test_mock_graph_still_pauses_for_review(self) -> None:
        from backend.app.graph.runner import ResearchGraphRunner
        from backend.tests.graph_fakes import (
            LAB_HITS,
            LAB_PAGES,
            FixtureRetrieval,
            client_for,
            scripted_behavior,
            success_roles,
        )

        retrieval = FixtureRetrieval(LAB_HITS, LAB_PAGES)
        client, _router = client_for(scripted_behavior(success_roles()))
        runner = ResearchGraphRunner(model_client=client, retrieval=retrieval)
        outcome = runner.start(_PAGE, run_id="run-obs", owner_id="owner-obs")
        self.assertTrue(outcome.interrupted)
        self.assertEqual(outcome.approval_status, "awaiting_review")
        names = {span.name for span in EXPORTER.get_finished_spans()}
        self.assertIn("research.run", names)
        self.assertIn("planner.invoke", names)
        self.assertIn("provider.call", names)
        self.assertIn("search.call", names)
        self.assertIn("source.fetch", names)
        review = [span for span in EXPORTER.get_finished_spans() if span.name == "human.review"]
        self.assertEqual(dict(review[-1].attributes or {})["status"], "paused")
        _assert_clean(self, _blob(EXPORTER.get_finished_spans()))
