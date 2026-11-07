"""Run the Milestone 2 graph for one leased job. The model is called only after the DB write."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import ResearchJob
from backend.app.graph.limits import GraphLimits
from backend.app.graph.runner import ResearchGraphRunner, RunNotPaused
from backend.app.jobs.timeutil import utc_now
from backend.app.schemas.research import ReviewDecision


@dataclass
class ExecutionResult:
    status: str
    provider_work_started: bool
    approval_status: str | None = None
    stop_reason: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    passages: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    report_markdown: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False


class GraphJobExecutor:
    def __init__(
        self,
        settings: Settings,
        *,
        checkpointer: Any = None,
        model_client: Any = None,
        retrieval: Any = None,
    ) -> None:
        self.settings = settings
        self.checkpointer = checkpointer
        self.model_client = model_client
        self.retrieval = retrieval

    def execute(self, session_factory: Callable[[], Session], job_id: str) -> ExecutionResult:
        session = session_factory()
        try:
            job = session.get(ResearchJob, job_id)
            if job is None:
                return ExecutionResult(
                    status="failed",
                    provider_work_started=False,
                    error_code="run_not_found",
                    error_detail="run_not_found",
                )
            if job.cancel_requested:
                return ExecutionResult(
                    status="cancelled",
                    provider_work_started=bool(job.provider_work_started),
                    error_code="cancelled",
                )
            budget = _budget(job.budget_json)
            resume_action = job.resume_action
            resume_comments = job.resume_comments or ""
            attempts = job.attempts
            topic = job.topic
            owner_id = job.owner_id
            job.provider_work_started = 1
            job.updated_at = utc_now()
            session.commit()
        except Exception:
            session.rollback()
            return ExecutionResult(
                status="failed",
                provider_work_started=False,
                error_code="database_unavailable",
                error_detail="database_unavailable",
            )
        finally:
            session.close()

        try:
            result = _run_graph(
                runner=self._runner(budget["max_model_calls"]),
                job_id=job_id,
                topic=topic,
                owner_id=owner_id,
                resume_action=resume_action,
                resume_comments=resume_comments,
                attempts=attempts,
                max_wall_clock_seconds=budget["max_wall_clock_seconds"],
            )
        except RunNotPaused:
            return ExecutionResult(
                status="failed",
                provider_work_started=True,
                error_code="review_not_paused",
                error_detail="review_not_paused",
            )
        except Exception as exc:
            return ExecutionResult(
                status="failed",
                provider_work_started=True,
                error_code="graph_error",
                error_detail=type(exc).__name__,
            )
        return _honor_cancel(session_factory, job_id, result)

    def _runner(self, max_model_calls: int) -> ResearchGraphRunner:
        client = self.model_client
        if client is None:
            from backend.app.providers.client import ModelClient

            client = ModelClient(self.settings)
        retrieval = self.retrieval
        if retrieval is None:
            from backend.app.research.retrieval import V1Retrieval

            retrieval = V1Retrieval()
        return ResearchGraphRunner(
            model_client=client,
            retrieval=retrieval,
            limits=GraphLimits(max_model_calls=max_model_calls).clamped(),
            checkpointer=self.checkpointer,
        )


def _budget(raw: str) -> dict[str, int]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "max_model_calls": _budget_value(parsed, "max_model_calls", 12),
        "max_wall_clock_seconds": _budget_value(parsed, "max_wall_clock_seconds", 180),
    }


def _budget_value(parsed: dict[str, Any], key: str, default: int) -> int:
    """Default only when the key is absent or null. Explicit 0 stays 0."""
    if key not in parsed or parsed[key] is None:
        return default
    return int(parsed[key])


def _run_graph(
    *,
    runner: Any,
    job_id: str,
    topic: str,
    owner_id: str,
    resume_action: str | None,
    resume_comments: str,
    attempts: int,
    max_wall_clock_seconds: int,
) -> ExecutionResult:
    # Explicit zero must reject before any graph work; do not start then expire.
    if max_wall_clock_seconds <= 0:
        return ExecutionResult(
            status="expired",
            provider_work_started=False,
            error_code="wall_clock",
            error_detail="wall_clock",
        )
    if resume_action:
        return _from_outcome(
            runner.resume(
                job_id,
                ReviewDecision(action=resume_action, comments=resume_comments),
            )
        )
    if attempts > 1:
        has_values, interrupted, state = runner.peek(job_id)
        if interrupted:
            return _from_state(state, status="review_required")
        if has_values:
            return _from_outcome(runner.continue_from_checkpoint(job_id))
    started = time.monotonic()
    outcome = runner.start(topic, owner_id=owner_id, run_id=job_id)
    result = _from_outcome(outcome)
    if time.monotonic() - started > max_wall_clock_seconds:
        result.status = "expired"
        result.error_code = "wall_clock"
        result.error_detail = "wall_clock"
    return result


def _honor_cancel(
    session_factory: Callable[[], Session],
    job_id: str,
    result: ExecutionResult,
) -> ExecutionResult:
    """If cancel landed while the graph ran, do not report completed or review_required.

    This does not interrupt an HTTP call already in flight. The check runs after
    start, resume, or continue_from_checkpoint returns.
    """
    if result.status not in {"completed", "review_required"}:
        return result
    try:
        session = session_factory()
    except Exception:
        return result
    try:
        job = session.get(ResearchJob, job_id)
        if job is not None and job.cancel_requested:
            result.status = "cancelled"
            result.error_code = "cancelled"
        return result
    except Exception:
        session.rollback()
        return result
    finally:
        session.close()


def _from_outcome(outcome: Any) -> ExecutionResult:
    state = dict(outcome.state or {})
    if outcome.interrupted:
        status = "review_required"
    elif state.get("terminal_failure") or outcome.approval_status == "failed":
        status = "failed"
    else:
        status = "completed"
    result = _from_state(state, status=status)
    if outcome.events:
        result.events = list(outcome.events)
    return result


def _from_state(state: dict[str, Any], *, status: str) -> ExecutionResult:
    usage = dict(state.get("usage") or {})
    usage["estimated_cost_usd"] = None
    return ExecutionResult(
        status=status,
        provider_work_started=True,
        approval_status=state.get("approval_status"),
        stop_reason=state.get("stop_reason"),
        events=list(state.get("events") or []),
        sources=list(state.get("sources") or []),
        passages=list(state.get("passages") or []),
        claims=list(state.get("claims") or []),
        report_markdown=_render_report(state.get("report_draft")),
        usage=usage,
    )


class LifespanGraphExecutor:
    """Open a Postgres checkpointer per job. SQLite keeps one in-memory saver.

    In-memory checkpoints do not survive a new process. Postgres checkpoints do,
    because each job opens PostgresSaver against the same database.
    """

    def __init__(self, settings: Settings, postgres_url: str | None) -> None:
        self.settings = settings
        self.postgres_url = postgres_url
        self._memory: Any = None

    def execute(self, session_factory: Callable[[], Session], job_id: str) -> ExecutionResult:
        if self.postgres_url:
            from backend.app.graph.checkpointer import open_postgres_checkpointer

            with open_postgres_checkpointer(self.postgres_url) as saver:
                return GraphJobExecutor(self.settings, checkpointer=saver).execute(session_factory, job_id)
        if self._memory is None:
            from backend.app.graph.checkpointer import build_checkpointer

            self._memory = build_checkpointer("memory")
        return GraphJobExecutor(self.settings, checkpointer=self._memory).execute(session_factory, job_id)


def _render_report(draft: object) -> str | None:
    if not isinstance(draft, dict):
        return None
    lines = [f"# {draft.get('title') or 'Research report'}", ""]
    for section in draft.get("sections") or []:
        if not isinstance(section, dict):
            continue
        lines.append(f"## {section.get('heading') or 'Section'}")
        lines.append(str(section.get("body") or ""))
        lines.append("")
    rendered = "\n".join(lines).strip()
    return rendered[:20000] or None
