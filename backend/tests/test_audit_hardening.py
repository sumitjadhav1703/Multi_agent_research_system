"""Regression tests for the audit-hardening fixes (graph, providers, fetch)."""
from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from backend.app.core.config import Settings
from backend.app.graph import GraphLimits, ResearchGraphRunner
from backend.app.graph.model_io import record_usage
from backend.app.graph.nodes import evidence_gate_node, select_prompt_passages, verify_node
from backend.app.graph.parsing import parse_json_object
from backend.app.jobs.executor import _from_outcome, _shared_model_client
from backend.app.providers.client import ModelClient
from backend.app.providers.mock_router import MockChoice, MockMessage, MockResponse, MockRouter, MockUsage
from backend.app.providers.usage import TokenUsage
from backend.app.research.evidence import materialize_hits
from backend.app.schemas.research import Claim, FetchResult, Passage, SearchHit
from backend.tests.graph_fakes import LAB_HITS, LAB_PAGES, FixtureRetrieval, success_roles
from backend.tests.helpers import mock_settings
from backend.tests.test_graph_workflow import _runner


def _passage(sq: str, n: int) -> Passage:
    return Passage(
        evidence_id=f"ev_{sq}_{n}", source_id=f"s_{sq}", subquestion_id=sq, quote="q", url="https://e.com", relevance_reason="r"
    )


class PassageSelectionTests(unittest.TestCase):
    def test_round_robin_reaches_followup_group(self) -> None:
        passages = [_passage("sq1", i) for i in range(1, 5)] + [_passage("sq2", 1), _passage("sq_followup", 1)]
        picked = [p.evidence_id for p in select_prompt_passages(passages, limit=4)]
        self.assertEqual(picked, ["ev_sq1_1", "ev_sq2_1", "ev_sq_followup_1", "ev_sq1_2"])


class GateAndFetchTests(unittest.TestCase):
    def test_no_followup_when_source_slots_are_full(self) -> None:
        runtime = SimpleNamespace(context=SimpleNamespace(limits=GraphLimits()))
        state = {
            "claims": [{"claim_id": "cl1", "status": "insufficient"}],
            "search_calls": 1,
            "sources": [{"source_id": f"s{i}"} for i in range(6)],
            "subquestions": [{"subquestion_id": "sq1", "question": "q"}],
            "passages": [{"x": 1}],
        }
        self.assertFalse(evidence_gate_node(state, runtime)["needs_followup"])

    def test_known_urls_are_not_fetched_again(self) -> None:
        fetched: list[str] = []

        def fetch(url: str) -> FetchResult:
            fetched.append(url)
            return FetchResult(url=url, text="Widget latency fell sharply in tests.", extraction_method="html")

        hits = [SearchHit(title="a", url="https://www.example.com/a/", snippet="s"), SearchHit(title="b", url="https://b.com/x", snippet="s")]
        sources, _p, _w = materialize_hits(
            subquestion_id="sq_followup",
            question="widget latency",
            hits=hits,
            fetch=fetch,
            fetch_budget=2,
            limits=GraphLimits(),
            retrieved_at="t",
            skip_urls=frozenset({"https://example.com/a"}),
        )
        self.assertEqual(fetched, ["https://b.com/x"])
        self.assertEqual(len(sources), 1)

    def test_pdf_hit_without_snippet_is_skipped(self) -> None:
        sources, passages, warnings = materialize_hits(
            subquestion_id="sq1",
            question="widget",
            hits=[SearchHit(title="p", url="https://e.com/a.pdf", snippet="")],
            fetch=lambda url: (_ for _ in ()).throw(AssertionError("no fetch")),
            fetch_budget=2,
            limits=GraphLimits(),
            retrieved_at="t",
        )
        self.assertEqual((sources, passages), ([], []))
        self.assertTrue(any(w.endswith(":empty") for w in warnings))


class PageHeadBoilerplateTests(unittest.TestCase):
    def test_passages_come_from_relevant_text_not_the_page_menu(self) -> None:
        # Live pages start with menus; the relevant text sits past the 2000-char excerpt cap.
        menu = "Skip to content Home About Shop Contact Login Menu. " * 50
        body = "Cold climate heat pumps keep heating efficiently below freezing in recent field tests."
        hit = SearchHit(title="t", url="https://e.com/heat", snippet=body)
        sources, passages, _w = materialize_hits(
            subquestion_id="sq1",
            question="How efficient are heat pumps for heating in cold climates?",
            hits=[hit],
            fetch=lambda url: FetchResult(url=url, text=menu + body, extraction_method="html"),
            fetch_budget=2,
            limits=GraphLimits(),
            retrieved_at="t",
        )
        self.assertTrue(passages)
        self.assertIn("heat pumps keep heating", passages[0].quote)
        self.assertIn(passages[0].quote, sources[0].excerpt)  # citations still point into the stored excerpt


class VerifyTests(unittest.TestCase):
    def test_all_auto_seed_claims_skip_the_llm(self) -> None:
        class Boom:
            def complete(self, *a, **k):
                raise AssertionError("verifier must not be called")

        runtime = SimpleNamespace(context=SimpleNamespace(limits=GraphLimits(), model_client=Boom()))
        claim = Claim(claim_id="cl_auto_1", text="x" * 50, evidence_ids=["ev1"], verification_reason="seed")
        passage = Passage(evidence_id="ev1", source_id="s", subquestion_id="sq1", quote="x" * 50, url="https://e.com", relevance_reason="r")
        out = verify_node({"claims": [claim.model_dump()], "passages": [passage.model_dump()]}, runtime)
        self.assertEqual(out["claims"][0]["status"], "insufficient")


class ParsingTests(unittest.TestCase):
    def test_leading_prose_with_braces_and_two_fences(self) -> None:
        text = 'Use {braces} freely.\n```json\n{"a": 1}\n```\nand\n```json\n{"b": 2}\n```'
        self.assertEqual(parse_json_object(text), {"a": 1})
        self.assertEqual(parse_json_object('note {not json} then {"k": {"n": 1}} tail {x}'), {"k": {"n": 1}})
        with self.assertRaises(ValueError):
            parse_json_object("no object here {")


class UsageTests(unittest.TestCase):
    def test_tokens_keep_summing_after_a_failed_call(self) -> None:
        usage = record_usage({"llm_calls": 0, "token_usage_complete": True}, None)
        self.assertFalse(usage["token_usage_complete"])
        ok = SimpleNamespace(usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5))
        usage = record_usage(usage, ok)
        self.assertEqual(usage["total_tokens"], 5)
        self.assertFalse(usage["token_usage_complete"])


class ProviderTests(unittest.TestCase):
    def test_empty_content_falls_back_to_fallback_alias(self) -> None:
        def behavior(model, messages, kwargs):
            text = "" if model == "rm-planner" else "ok"
            return MockResponse(
                choices=[MockChoice(message=MockMessage(content=text))],
                model="mock/free-model" if model == "rm-planner" else "mock/free-fallback",
                usage=MockUsage(1, 1, 2),
            )

        settings = mock_settings()
        router = MockRouter(behavior=behavior)
        result = ModelClient(settings, router=router).complete("planner", [{"role": "user", "content": "x"}])
        self.assertEqual(result.content, "ok")
        self.assertEqual([c["model"] for c in router.calls], ["rm-planner", "rm-planner-fallback"])

    def test_meta_last_resort_is_off_by_default_even_with_a_key(self) -> None:
        settings = mock_settings(META_API_KEY="k", META_LAST_RESORT_ENABLED="")
        self.assertFalse(settings.meta_last_resort_active())
        self.assertTrue(mock_settings(META_API_KEY="k", META_LAST_RESORT_ENABLED="true").meta_last_resort_active())

    def test_meta_last_resort_requires_allowlisted_model(self) -> None:
        with self.assertRaises(ValueError):
            mock_settings(META_API_KEY="k", META_LAST_RESORT_ENABLED="true", FREE_MODEL_ALLOWLIST="mock/free-model,mock/free-fallback")

    def test_default_chain_drops_gemini_and_mistral(self) -> None:
        settings = Settings(_env_file=None, USE_MOCK_PROVIDER="true")
        for model in settings.allowlist | set(settings.configured_model_ids()):
            self.assertFalse(model.startswith(("gemini/", "mistral/")), model)
        self.assertIn(settings.meta_last_resort_model, settings.allowlist)  # enabling it must not fail boot

    def test_nvidia_nim_models_use_the_nvidia_key(self) -> None:
        from backend.app.providers.router_factory import _api_key_for_model

        keyed = Settings(_env_file=None, USE_MOCK_PROVIDER="true", NVIDIA_NIM_API_KEY="nv")
        self.assertEqual(_api_key_for_model(keyed, "nvidia_nim/meta/llama-3.3-70b-instruct"), "nv")


class ExecutorTests(unittest.TestCase):
    def test_model_client_is_cached_per_settings(self) -> None:
        settings = mock_settings()
        self.assertIs(_shared_model_client(settings), _shared_model_client(settings))
        self.assertIsNot(_shared_model_client(settings), _shared_model_client(mock_settings()))

    def test_wall_clock_deadline_expires_the_run(self) -> None:
        runner, _router = _runner(success_roles(1), FixtureRetrieval(LAB_HITS, LAB_PAGES))
        runner.deadline = time.monotonic() - 1
        outcome = runner.start("Widget latency", run_id="deadline")
        self.assertTrue(outcome.expired)
        self.assertFalse(outcome.interrupted)
        result = _from_outcome(outcome)
        self.assertEqual((result.status, result.stop_reason, result.error_code), ("expired", "wall_clock", "wall_clock"))

    def test_runs_budget_shows_clamped_model_calls(self) -> None:
        from backend.app.api.v1.runs import server_budgets

        self.assertEqual(server_budgets(mock_settings(MAX_MODEL_CALLS_PER_RUN="99"))["max_model_calls"], 12)


class EgressDeadlineTests(unittest.TestCase):
    def test_read_capped_enforces_overall_deadline(self) -> None:
        from backend.app.security.egress_fetch import _read_capped

        class Drip:
            def read(self, n):
                return b"x"

        with self.assertRaises(TimeoutError):
            _read_capped(Drip(), 1000, time.monotonic() - 1)


if __name__ == "__main__":
    unittest.main()
