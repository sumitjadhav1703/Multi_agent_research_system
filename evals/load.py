"""Load and validate the golden set and fixture runs."""
from __future__ import annotations

import json
from pathlib import Path

DATASET_VERSION = "golden-v0.1"
CATEGORIES = frozenset(
    {
        "factual",
        "multi_hop",
        "contradictory",
        "stale_source",
        "current_information",
        "insufficient_evidence",
        "prompt_injection",
    }
)
BEHAVIORS = frozenset(
    {
        "answer",
        "preserve_contradiction",
        "reject_stale",
        "require_dated_source",
        "insufficient_evidence",
        "refuse_injection",
    }
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_dataset_path() -> Path:
    return repo_root() / "evals" / "dataset" / "golden_v0.jsonl"


def default_runs_path() -> Path:
    return repo_root() / "evals" / "fixtures" / "runs.json"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_number}: expected an object")
        rows.append(item)
    return rows


def load_runs(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{path}: expected a non-empty list of run artifacts")
    return payload


def validate_golden(cases: list[dict]) -> None:
    if len(cases) < 30:
        raise ValueError(f"golden set has {len(cases)} cases; starter set must contain at least 30")
    seen: set[str] = set()
    counts = {category: 0 for category in CATEGORIES}
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or case_id in seen:
            raise ValueError(f"duplicate or missing id: {case_id!r}")
        seen.add(case_id)
        if case.get("dataset_version") != DATASET_VERSION:
            raise ValueError(f"{case_id}: dataset_version must be {DATASET_VERSION}")
        category = case.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"{case_id}: unknown category {category!r}")
        counts[category] += 1
        behavior = case.get("expected_behavior")
        if behavior not in BEHAVIORS:
            raise ValueError(f"{case_id}: unknown expected_behavior {behavior!r}")
        _require_text(case, "question")
        _require_text(case, "intended_task")
        _require_text(case, "reference_answer")
        facts = case.get("reference_facts")
        if not isinstance(facts, list) or not facts or not all(isinstance(item, str) and item.strip() for item in facts):
            raise ValueError(f"{case_id}: reference_facts must be a non-empty list of strings")
        subquestions = case.get("subquestions")
        if not isinstance(subquestions, list) or not subquestions:
            raise ValueError(f"{case_id}: subquestions must be a non-empty list")
        if category == "multi_hop" and len(subquestions) < 2:
            raise ValueError(f"{case_id}: multi-hop cases need at least two subquestions")
        passages = case.get("reference_passages")
        if not isinstance(passages, list) or not passages:
            raise ValueError(f"{case_id}: reference_passages must be a non-empty list")
        for passage in passages:
            if passage.get("kind") != "paraphrase":
                raise ValueError(f"{case_id}: only paraphrase passages are allowed in v0.1")
            if not str(passage.get("url", "")).startswith("https://"):
                raise ValueError(f"{case_id}: passage URL must be https")
            if not str(passage.get("text", "")).strip():
                raise ValueError(f"{case_id}: empty passage text")
            if passage.get("fetched") is not False:
                raise ValueError(f"{case_id}: passage.fetched must be false; this set is not a crawl snapshot")
        review = case.get("review") or {}
        if review.get("status") != "author_reviewed":
            raise ValueError(f"{case_id}: review.status must stay author_reviewed until a second review")
        if review.get("independent_second_review") is not False:
            raise ValueError(f"{case_id}: independent second review has not happened")
        if case.get("snapshot_status") != "not_frozen":
            raise ValueError(f"{case_id}: snapshot_status must stay not_frozen")
        if behavior == "preserve_contradiction":
            rows = case.get("contradictions") or []
            if not rows or not rows[0].get("side_a") or not rows[0].get("side_b"):
                raise ValueError(f"{case_id}: contradiction cases need both sides")
        if behavior == "reject_stale" and not case.get("stale_before"):
            raise ValueError(f"{case_id}: stale cases need stale_before")
        if behavior == "refuse_injection":
            injection = case.get("injection") or {}
            if not injection.get("success_markers") and not injection.get("forbidden_tool_urls"):
                raise ValueError(f"{case_id}: injection cases need a marker or a forbidden URL")
        if behavior == "require_dated_source" and not str(case.get("reference_answer", "")).startswith("TIME_DEPENDENT"):
            raise ValueError(f"{case_id}: dated cases must prefix reference_answer with TIME_DEPENDENT")
        phrases = case.get("required_report_phrases") or []
        if behavior in {"require_dated_source", "refuse_injection", "insufficient_evidence"} and phrases:
            raise ValueError(f"{case_id}: do not lock time-varying or refusal cases to a required phrase")
    missing = [name for name, count in counts.items() if count < 3]
    if missing:
        raise ValueError(f"categories below 3 cases: {missing}")


def _require_text(case: dict, field: str) -> None:
    value = case.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{case.get('id')}: {field} must be non-empty text")
