"""Dataset shape and deterministic evaluators. No model calls."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from evals.checks import canonical_url, evaluate_run, issue_codes, static_url_problem
from evals.dataset.golden_v0 import CASES, dumps
from evals.load import default_dataset_path, default_runs_path, load_jsonl, load_runs, validate_golden

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


class DatasetTests(unittest.TestCase):
    def test_jsonl_matches_authoring_module(self) -> None:
        path = default_dataset_path()
        self.assertEqual(path.read_text(encoding="utf-8"), dumps())
        cases = load_jsonl(path)
        validate_golden(cases)
        self.assertEqual([case["id"] for case in cases], [case["id"] for case in CASES])
        self.assertGreaterEqual(len(cases), 30)

    def test_required_categories_are_present(self) -> None:
        counts: dict[str, int] = {}
        for case in CASES:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        for category in (
            "factual",
            "multi_hop",
            "contradictory",
            "stale_source",
            "current_information",
            "insufficient_evidence",
            "prompt_injection",
        ):
            self.assertGreaterEqual(counts.get(category, 0), 3, category)
        self.assertTrue(any(case["category"] == "multi_hop" and len(case["subquestions"]) >= 2 for case in CASES))
        self.assertTrue(all(case["review"]["independent_second_review"] is False for case in CASES))
        self.assertTrue(all(case["snapshot_status"] == "not_frozen" for case in CASES))


class DeterministicTests(unittest.TestCase):
    def test_fixture_pack_matches_expected_codes(self) -> None:
        cases = {case["id"]: case for case in load_jsonl(default_dataset_path())}
        runs = load_runs(default_runs_path())
        self.assertGreaterEqual(len(runs), 15)
        systems = {run["system"] for run in runs}
        self.assertEqual(systems, {"fixture"})
        for run in runs:
            issues = evaluate_run(run, cases[run["case_id"]])
            self.assertEqual(issue_codes(issues), sorted(run["expect_issue_codes"]), run["run_id"])

    def test_cli_pack_exits_zero(self) -> None:
        completed = subprocess.run(
            [PYTHON, "-m", "evals.cli", "deterministic"],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("metric_kind=deterministic", completed.stdout)
        self.assertNotIn("deepeval", sys.modules)

    def test_canonical_url_matches_backend(self) -> None:
        try:
            from backend.app.research.retrieval import canonical_url as backend_canonical
        except Exception as exc:
            self.skipTest(f"backend retrieval could not be imported: {type(exc).__name__}: {exc}")
        samples = [
            "https://www.Example.com/lab/",
            "https://example.com/lab?b=1&a=2",
            "https://example.com/lab?a=2&b=1",
        ]
        for sample in samples:
            self.assertEqual(canonical_url(sample), backend_canonical(sample))

    def test_static_url_blocks_private_targets_without_dns(self) -> None:
        blocked = [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1/",
            "http://10.1.2.3/",
            "http://192.168.0.5/",
            "http://2130706433/",
            "http://localhost/admin",
            "http://metadata.google.internal/",
            "http://example.com:22/",
            "https://user:pass@example.com/",
            "file:///etc/passwd",
            "http://[::1]/",
            "http://0177.0.0.1/",
            "http://127.1/",
            "http://0x7f.1/",
            "http://0x7f000001/",
        ]
        for url in blocked:
            self.assertIsNotNone(static_url_problem(url), url)
        self.assertIsNone(static_url_problem("https://example.com/lab"))

    def test_empty_excerpt_and_none_usage_and_retrieved_at(self) -> None:
        base = {
            "sources": [{"source_id": "s", "url": "https://a.example/x", "excerpt": "  ", "retrieved_at": "2026-11-07"}],
            "passages": [{"evidence_id": "e", "source_id": "s", "url": "https://a.example/x", "quote": "anything"}],
            "claims": [{"claim_id": "c", "evidence_ids": ["e"], "status": "supported"}],
        }
        self.assertIn("quote_not_in_source", issue_codes(evaluate_run(base, None)))
        run = {**base, "usage": {"search_calls": None, "max_search_calls": None}, "tool_calls": [{"name": "web_search"}]}
        evaluate_run(run, None)  # must not raise
        golden = {"expected_behavior": "require_dated_source"}
        self.assertIn("undated_current_claim", issue_codes(evaluate_run(base, golden)))

    def test_contradiction_hidden_in_sidecar_is_not_preservation(self) -> None:
        golden = next(case for case in CASES if case["id"] == "g014")
        run = {
            "report_text": "Pluto is a dwarf planet and was called the ninth planet.",
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "Pluto is a dwarf planet and was called the ninth planet.",
                    "evidence_ids": [],
                    "status": "contradictory",
                }
            ],
            "passages": [],
            "sources": [],
            "contradictions": [
                {
                    "contradiction_id": "k1",
                    "summary": "This summary never reached the report body.",
                }
            ],
            "tool_calls": [],
            "usage": {},
            "quota": {},
        }
        self.assertIn("contradiction_not_in_report", issue_codes(evaluate_run(run, golden)))

    def test_unlabeled_run_with_issues_is_a_failure(self) -> None:
        path = ROOT / "evals" / "fixtures" / "runs.json"
        runs = json.loads(path.read_text(encoding="utf-8"))
        broken = dict(runs[0])
        broken.pop("expect_issue_codes")
        broken["run_id"] = "unlabeled"
        broken["quota"] = {"identity_already_consumed": True, "start_accepted": True}
        target = ROOT / "evals" / "fixtures" / "_tmp_unlabeled.json"
        target.write_text(json.dumps([broken]), encoding="utf-8")
        try:
            completed = subprocess.run(
                [PYTHON, "-m", "evals.cli", "deterministic", "--runs", str(target)],
                cwd=ROOT,
                env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            target.unlink(missing_ok=True)
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("unlabeled_issues=1", completed.stdout)
