"""Offline evaluation commands.

deterministic  — Python checks only. Safe for a local test run.
judge          — DeepEval LLM judge. Refuses unless explicitly confirmed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.checks import evaluate_run, issue_codes
from evals.judge import JudgeConfigError, JudgeDependencyError, JudgeDisabled, execute_judge
from evals.load import default_dataset_path, default_runs_path, load_jsonl, load_runs, validate_golden


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    deterministic = sub.add_parser("deterministic")
    deterministic.add_argument("--dataset", type=Path, default=default_dataset_path())
    deterministic.add_argument("--runs", type=Path, default=default_runs_path())

    judge = sub.add_parser("judge")
    judge.add_argument("--dataset", type=Path, default=default_dataset_path())
    judge.add_argument("--runs", type=Path, default=default_runs_path())
    judge.add_argument("--output", type=Path, default=None)
    judge.add_argument("--confirm-offline", action="store_true")
    judge.add_argument("--dry-run", action="store_true")
    judge.add_argument("--allow-version-mismatch", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "deterministic":
            return _deterministic(args.dataset, args.runs)
        return _judge(args)
    except (OSError, ValueError, JudgeDisabled, JudgeDependencyError, JudgeConfigError) as exc:
        print(str(exc), file=sys.stderr)
        if isinstance(exc, JudgeDependencyError):
            return 3
        if isinstance(exc, (JudgeDisabled, JudgeConfigError)):
            return 2
        return 2


def _deterministic(dataset_path: Path, runs_path: Path) -> int:
    cases = load_jsonl(dataset_path)
    validate_golden(cases)
    runs = load_runs(runs_path)
    by_case = {case["id"]: case for case in cases}
    mismatches = 0
    structural = 0
    for run in runs:
        golden = by_case.get(run.get("case_id"))
        issues = evaluate_run(run, golden)
        actual = issue_codes(issues)
        expected = run.get("expect_issue_codes")
        print(f"{run.get('run_id')}\t{run.get('case_id')}\t{','.join(actual) if actual else 'pass'}")
        if expected is None:
            structural += len(actual)
        elif sorted(expected) != actual:
            mismatches += 1
            print(f"  expected {sorted(expected)}", file=sys.stderr)
    print(
        f"dataset={len(cases)} runs={len(runs)} fixture_mismatches={mismatches} "
        f"unlabeled_issues={structural}"
    )
    print("metric_kind=deterministic. These rows are not LLM-judge scores.")
    return 1 if mismatches or structural else 0


def _judge(args: argparse.Namespace) -> int:
    if not args.confirm_offline:
        raise JudgeDisabled(
            "Refusing the judge. Re-run with RM_EVAL_JUDGE=1 and --confirm-offline. "
            "This does not score public demo requests."
        )
    cases = load_jsonl(args.dataset)
    validate_golden(cases)
    runs = load_runs(args.runs)
    report = execute_judge(
        cases,
        runs,
        measure=not args.dry_run,
        allow_version_mismatch=args.allow_version_mismatch,
    )
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output} measured={report['measured']} cases={report['case_count']}")
    else:
        print(text)
    if report["measured"] and any(
        metric.get("status") == "error"
        for case in report["cases"]
        for metric in case.get("metrics") or []
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
