"""The judge stays off unless a person opts in. Scores are never invented."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evals.dataset.golden_v0 import CASES
from evals.judge import (
    JudgeConfigError,
    JudgeDisabled,
    execute_judge,
    plan_judge_metrics,
)
from evals.load import default_runs_path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
DEEPEVAL_PROBE = Path("/tmp/deepeval_inspect")


class PlanningTests(unittest.TestCase):
    def test_planning_does_not_import_deepeval(self) -> None:
        sys.modules.pop("deepeval", None)
        factual = next(case for case in CASES if case["id"] == "g001")
        dated = next(case for case in CASES if case["id"] == "g021")
        ready = {row["name"]: row["status"] for row in plan_judge_metrics(factual, {"report_text": "Canberra.", "passages": [{"quote": "Canberra."}], "tool_calls": [{"name": "web_search", "arguments": {"query": "capital"}}]})}
        self.assertEqual(ready["faithfulness"], "eligible")
        self.assertEqual(ready["tool_correctness"], "eligible")
        self.assertEqual(ready["task_completion"], "skipped")
        self.assertEqual(ready["plan_adherence"], "skipped")
        self.assertEqual(ready["step_efficiency"], "skipped")
        dated_rows = {row["name"]: row["status"] for row in plan_judge_metrics(dated, {"report_text": "Dated.", "passages": [{"quote": "Dated."}]})}
        self.assertEqual(dated_rows["contextual_precision"], "skipped")
        self.assertEqual(dated_rows["contextual_recall"], "skipped")
        self.assertNotIn("deepeval", sys.modules)
        self.assertTrue(all(row["score"] is None for row in plan_judge_metrics(factual, {})))
        self.assertTrue(all(row["kind"] == "llm_judge" for row in plan_judge_metrics(factual, {})))

    def test_disabled_and_missing_key_do_not_score(self) -> None:
        saved = {
            key: os.environ.get(key)
            for key in (
                "RM_EVAL_JUDGE",
                "META_API_KEY",
                "MODEL_API_KEY",
                "LLAMA_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
            )
        }
        try:
            os.environ.pop("RM_EVAL_JUDGE", None)
            with self.assertRaises(JudgeDisabled):
                execute_judge(CASES[:1], [{"case_id": "g001", "system": "fixture"}], measure=False)
            os.environ["RM_EVAL_JUDGE"] = "1"
            os.environ.pop("META_API_KEY", None)
            os.environ.pop("MODEL_API_KEY", None)
            os.environ.pop("LLAMA_API_KEY", None)
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            with self.assertRaises(JudgeConfigError):
                execute_judge(CASES[:1], [{"case_id": "g001", "system": "fixture"}], measure=True)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_errors_leave_score_null(self) -> None:
        class Boom:
            def measure(self, _test_case: object) -> float:
                raise RuntimeError("judge transport failed")

        os.environ["RM_EVAL_JUDGE"] = "1"
        try:
            report = execute_judge(
                CASES[:1],
                [{"case_id": "g001", "system": "fixture", "report_text": "Canberra.", "passages": [{"quote": "Canberra."}]}],
                measure=True,
                metric_builder=lambda _name: Boom(),
            )
        finally:
            os.environ.pop("RM_EVAL_JUDGE", None)
        scored = [row for row in report["cases"][0]["metrics"] if row["status"] == "error"]
        self.assertTrue(scored)
        self.assertTrue(all(row["score"] is None for row in scored))
        self.assertFalse(report["cases"][0]["is_benchmark"])
        self.assertEqual(report["kind"], "llm_judge")


class CommandGateTests(unittest.TestCase):
    def test_cli_refuses_without_confirmation_or_install(self) -> None:
        bare = self._run(["-m", "evals.cli", "judge"])
        self.assertEqual(bare.returncode, 2, bare.stderr)
        self.assertIn("--confirm-offline", bare.stderr)

        flagged = self._run(
            ["-m", "evals.cli", "judge", "--confirm-offline", "--dry-run"],
            extra_env={"RM_EVAL_JUDGE": "1"},
        )
        # Return 3 when DeepEval is missing; 0 when it is installed and dry-run constructs metrics.
        if flagged.returncode == 3:
            self.assertIn("evals/requirements.txt", flagged.stderr)
            self.assertNotIn("score", flagged.stdout)
        else:
            self.assertEqual(flagged.returncode, 0, flagged.stderr)
            self.assertIn("llm_judge", flagged.stdout)

    def test_public_trees_and_ci_do_not_reference_deepeval(self) -> None:
        import_deepeval = re.compile(r"^\s*(?:import deepeval\b|from deepeval\b)", re.MULTILINE)
        roots = [ROOT / "backend" / "app", ROOT / "frontend" / "src", ROOT / "tests"]
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix not in {".py", ".ts", ".tsx", ".yml", ".yaml"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertIsNone(import_deepeval.search(text), str(path))
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        requirements = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("deepeval", workflow.lower())
        self.assertNotIn("deepeval", requirements.lower())

    @unittest.skipUnless(DEEPEVAL_PROBE.is_dir(), "local DeepEval probe directory is absent")
    def test_dry_run_constructs_litellm_model_without_reading_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("RM_EVAL_LEAK_SENTINEL=needle-do-not-load\n", encoding="utf-8")
            output = Path(tmp) / "judge.json"
            completed = self._run(
                [
                    "-m",
                    "evals.cli",
                    "judge",
                    "--confirm-offline",
                    "--dry-run",
                    "--runs",
                    str(default_runs_path()),
                    "--output",
                    str(output),
                ],
                extra_env={
                    "RM_EVAL_JUDGE": "1",
                    "PYTHONPATH": f"{ROOT}{os.pathsep}{DEEPEVAL_PROBE}",
                    "DEEPEVAL_DISABLE_DOTENV": "1",
                    "LITELLM_MODE": "PRODUCTION",
                },
                cwd=tmp,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertNotIn("needle-do-not-load", text)
            self.assertNotIn("needle-do-not-load", completed.stdout)
            self.assertNotIn("needle-do-not-load", completed.stderr)
            report = json.loads(text)
        self.assertFalse(report["measured"])
        self.assertEqual(report["evaluator_model"], "meta/muse-spark-1.3-contributor")
        self.assertEqual(report["deepeval_version"], "4.3.3")
        self.assertEqual(report["constructor_probe"]["faithfulness"], "FaithfulnessMetric")
        self.assertEqual(report["constructor_probe"]["plan_adherence"], "PlanAdherenceMetric")
        self.assertTrue(
            all(metric["score"] is None for case in report["cases"] for metric in case["metrics"])
        )

    def _run(
        self,
        args: list[str],
        extra_env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin", "LITELLM_MODE": "PRODUCTION"}
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [PYTHON, *args],
            cwd=cwd or str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
