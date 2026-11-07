"""Controlled DeepEval harness.

Importing this module does not import DeepEval. Metric objects are built only
after RM_EVAL_JUDGE=1, --confirm-offline, and prepare_eval_environment().
Nothing here is called from the public FastAPI path.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from evals import DEEPEVAL_PIN, EVALUATOR_MODEL
from evals.load import DATASET_VERSION

JUDGE_FLAG = "RM_EVAL_JUDGE"
LIBRARY_DEFAULT_THRESHOLD = 0.5

# DeepEval 4.3.3 defaults. Not a calibrated ResearchMind pass bar.
METRIC_NOTES = {
    "faithfulness": "LLM judge. Needs the report and retrieved passage text.",
    "answer_relevancy": "LLM judge. Needs the question and the report.",
    "contextual_precision": "LLM judge. Needs a stable expected answer and retrieved passages.",
    "contextual_recall": "LLM judge. Needs a stable expected answer and retrieved passages.",
    "tool_correctness": "LLM judge in DeepEval 4.3.3. Needs tools_called and expected_tools.",
    "argument_correctness": "LLM judge. Needs tools_called.",
    "task_completion": "Trace metric in DeepEval 4.3.3 (requires_trace). Not run without a trace.",
    "plan_adherence": "Trace metric. Needs a trace that contains a plan. Not attached to the public graph.",
    "step_efficiency": "Trace metric. Needs a trace. Not attached to the public graph.",
}


class JudgeDisabled(RuntimeError):
    pass


class JudgeDependencyError(RuntimeError):
    pass


class JudgeConfigError(RuntimeError):
    pass


def judge_enabled() -> bool:
    return os.environ.get(JUDGE_FLAG) == "1"


def prepare_eval_environment() -> None:
    """Block DeepEval and LiteLLM from reading a .env file on import."""
    os.environ["DEEPEVAL_DISABLE_DOTENV"] = "1"
    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
    os.environ["LITELLM_MODE"] = "PRODUCTION"


def plan_judge_metrics(golden: dict, run: dict | None) -> list[dict[str, Any]]:
    """Decide which judge metrics are eligible. Does not import DeepEval."""
    run = run or {}
    report = (run.get("report_text") or "").strip()
    passages = _passage_texts(run)
    tools = run.get("tool_calls") or []
    expected_tools = golden.get("expected_tools") or []
    trace = run.get("trace") if isinstance(run.get("trace"), dict) else None
    stable_answer = not str(golden.get("reference_answer", "")).startswith("TIME_DEPENDENT")
    plans = [
        ("faithfulness", bool(report and passages), "report and retrieval context are required"),
        ("answer_relevancy", bool(report), "report text is required"),
        (
            "contextual_precision",
            bool(report and passages and stable_answer),
            "skipped for TIME_DEPENDENT reference answers; no stable expected output",
        ),
        (
            "contextual_recall",
            bool(report and passages and stable_answer),
            "skipped for TIME_DEPENDENT reference answers; no stable expected output",
        ),
        (
            "tool_correctness",
            bool(tools and expected_tools),
            "tools_called and expected_tools are required",
        ),
        ("argument_correctness", bool(tools), "tools_called are required"),
        ("task_completion", trace is not None, "requires a DeepEval trace; public graph is not instrumented"),
        ("plan_adherence", trace is not None, "requires a DeepEval trace with a plan"),
        ("step_efficiency", trace is not None, "requires a DeepEval trace"),
    ]
    rows = []
    for name, eligible, skip_reason in plans:
        rows.append(
            {
                "name": name,
                "kind": "llm_judge",
                "threshold": LIBRARY_DEFAULT_THRESHOLD,
                "threshold_note": "DeepEval 4.3.3 library default, not a calibrated ResearchMind bar",
                "status": "eligible" if eligible else "skipped",
                "reason": None if eligible else skip_reason,
                "score": None,
                "note": METRIC_NOTES[name],
            }
        )
    return rows


def execute_judge(
    cases: list[dict],
    runs: list[dict],
    *,
    measure: bool,
    allow_version_mismatch: bool = False,
    metric_builder: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Score saved runs, or describe the metrics without calling a model.

    measure=False is the dry run. It still imports DeepEval when metric_builder
    is left as the real builder, so a missing install fails before any score exists.
    """
    if not judge_enabled():
        raise JudgeDisabled(
            "Set RM_EVAL_JUDGE=1 to run the offline judge. Public requests must not set this."
        )
    prepare_eval_environment()
    if measure and metric_builder is None and not _credential_present():
        raise JudgeConfigError(
            "Export GEMINI_API_KEY or GOOGLE_API_KEY in the process environment. "
            "This command does not read a .env file."
        )
    version = None
    builder = metric_builder
    constructor_probe: dict[str, str] | None = None
    if builder is None:
        version = _import_deepeval_version(allow_version_mismatch)
        model = _build_model()

        def builder(name: str, _model: Any = model) -> Any:
            return _build_metric(name, _model)

        if not measure:
            constructor_probe = {name: builder(name).__class__.__name__ for name in METRIC_NOTES}
    by_case = {case["id"]: case for case in cases}
    case_rows = []
    for run in runs:
        golden = by_case.get(run.get("case_id"))
        if golden is None:
            case_rows.append(
                {
                    "case_id": run.get("case_id"),
                    "system": run.get("system"),
                    "metrics": [],
                    "error": "case_id is not in the golden set",
                }
            )
            continue
        metrics = []
        for planned in plan_judge_metrics(golden, run):
            row = dict(planned)
            if row["status"] != "eligible":
                metrics.append(row)
                continue
            if not measure:
                row["status"] = "not_measured"
                row["reason"] = "dry run; judge was not called"
                metrics.append(row)
                continue
            try:
                metric = builder(row["name"])
                test_case = _test_case(golden, run)
                score = metric.measure(test_case)
            except Exception as exc:  # noqa: BLE001 — record the failure, do not invent a score
                row["status"] = "error"
                row["score"] = None
                row["reason"] = f"{type(exc).__name__}: {exc}"
                metrics.append(row)
                continue
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                row["status"] = "error"
                row["score"] = None
                row["reason"] = "judge returned no numeric score"
            else:
                row["status"] = "scored"
                row["score"] = float(score)
                row["reason"] = getattr(metric, "reason", None)
            metrics.append(row)
        case_rows.append(
            {
                "case_id": golden["id"],
                "system": run.get("system"),
                "is_benchmark": run.get("system") in {"v1", "v2a", "v2b"},
                "metrics": metrics,
            }
        )
    return {
        "kind": "llm_judge",
        "measured": measure,
        "dataset_version": DATASET_VERSION,
        "deepeval_version": version,
        "deepeval_pin": DEEPEVAL_PIN,
        "evaluator_model": EVALUATOR_MODEL,
        "run_date": date.today().isoformat(),
        "case_count": len(case_rows),
        "cases": case_rows,
        "constructor_probe": constructor_probe,
        "note": "LLM-judge rows are not deterministic citation checks. Null scores are not zeros.",
    }


def _credential_present() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _import_deepeval_version(allow_version_mismatch: bool) -> str:
    try:
        import deepeval
    except ImportError as exc:
        raise JudgeDependencyError(
            "DeepEval is not installed. For a controlled run only: "
            "uv pip install --python /tmp/rm_v2_venv/bin/python -r evals/requirements.txt. "
            "Do not add it to CI or the public API environment for this milestone."
        ) from exc
    version = str(getattr(deepeval, "__version__", "unknown"))
    if version != DEEPEVAL_PIN and not allow_version_mismatch:
        raise JudgeConfigError(
            f"Installed DeepEval {version} does not match pin {DEEPEVAL_PIN}. "
            "Refusing so a run cannot be compared with an unpinned judge. "
            "Pass --allow-version-mismatch only when you will record the difference."
        )
    return version


def _build_model() -> Any:
    from deepeval.models import LiteLLMModel

    # Do not pass api_key. LiteLLM reads the process environment at call time.
    return LiteLLMModel(model=EVALUATOR_MODEL, temperature=0)


def _build_metric(name: str, model: Any) -> Any:
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ArgumentCorrectnessMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        FaithfulnessMetric,
        PlanAdherenceMetric,
        StepEfficiencyMetric,
        TaskCompletionMetric,
        ToolCorrectnessMetric,
    )

    classes = {
        "faithfulness": FaithfulnessMetric,
        "answer_relevancy": AnswerRelevancyMetric,
        "contextual_precision": ContextualPrecisionMetric,
        "contextual_recall": ContextualRecallMetric,
        "tool_correctness": ToolCorrectnessMetric,
        "argument_correctness": ArgumentCorrectnessMetric,
        "task_completion": TaskCompletionMetric,
        "plan_adherence": PlanAdherenceMetric,
        "step_efficiency": StepEfficiencyMetric,
    }
    return classes[name](
        threshold=LIBRARY_DEFAULT_THRESHOLD,
        model=model,
        eval_mode="llm",
        include_reason=True,
        async_mode=False,
        verbose_mode=False,
    )


def _test_case(golden: dict, run: dict) -> Any:
    from deepeval.test_case import LLMTestCase, ToolCall

    tools = [
        ToolCall(name=call.get("name") or "", input_parameters=call.get("arguments") or {})
        for call in run.get("tool_calls") or []
    ]
    expected = [ToolCall(name=name) for name in golden.get("expected_tools") or []]
    test_case = LLMTestCase(
        input=golden["question"],
        actual_output=run.get("report_text") or "",
        expected_output=None if str(golden.get("reference_answer", "")).startswith("TIME_DEPENDENT") else golden.get("reference_answer"),
        retrieval_context=_passage_texts(run) or None,
        tools_called=tools or None,
        expected_tools=expected or None,
    )
    trace = run.get("trace")
    if isinstance(trace, dict):
        test_case._trace_dict = trace
    return test_case


def _passage_texts(run: dict) -> list[str]:
    texts = []
    for passage in run.get("passages") or []:
        quote = (passage.get("quote") or "").strip()
        if quote:
            texts.append(quote)
    return texts
