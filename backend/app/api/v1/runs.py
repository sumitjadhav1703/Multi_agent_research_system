"""Research run commands. SSE replay is Milestone 4; this route returns the event log."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.app.api.v1.deps import bearer_token, call_db, current_settings, get_session, wake_consumer
from backend.app.api.v1.snapshot import run_usage
from backend.app.core.config import Settings
from backend.app.db.models import JobEvent, ResearchJob
from backend.app.graph.limits import GraphLimits
from backend.app.observability import start_span
from backend.app.jobs.quota import (
    cancel_run,
    get_owned_job,
    identity_from_token,
    list_events,
    request_review,
    start_run,
)

router = APIRouter(tags=["research-runs"])


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    comments: str = ""


def server_budgets(settings: Settings) -> dict[str, int]:
    return {
        "max_subquestions": 3,
        "max_parallel_workers": 2,
        "max_sources": 6,
        "max_search_calls": 4,
        "max_evidence_retries": 1,
        "max_revisions": 1,
        "max_model_calls": GraphLimits(max_model_calls=settings.max_model_calls_per_run).clamped().max_model_calls,
        "max_wall_clock_seconds": settings.max_run_wall_clock_seconds,
    }


def public_job(job: ResearchJob, *, reused: bool | None = None) -> dict[str, object]:
    try:
        budgets = json.loads(job.budget_json)
    except json.JSONDecodeError:
        budgets = {}
    body: dict[str, object] = {
        "run_id": job.id,
        "status": job.status,
        "topic": job.topic,
        "approval_status": job.approval_status,
        "stop_reason": job.stop_reason,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "attempts": job.attempts,
        "cancel_requested": bool(job.cancel_requested),
        "provider_work_started": bool(job.provider_work_started),
        "error_code": job.error_code,
        "budgets": budgets,
    }
    if reused is not None:
        body["reused"] = reused
    return body


def public_event(row: JobEvent) -> dict[str, object]:
    try:
        payload = json.loads(row.payload)
    except json.JSONDecodeError:
        payload = {}
    return {
        "sequence_id": row.sequence_id,
        "type": row.event_type,
        "payload": payload,
        "created_at": row.created_at,
    }


@router.post("/research-runs")
def create_run(
    body: StartRunRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    settings = current_settings(request)
    identity = call_db(lambda: identity_from_token(session, token))

    def _start():
        return start_run(
            session,
            identity_id=identity.id,
            topic=body.topic,
            idempotency_key=idempotency_key or "",
            max_active=settings.global_max_active_runs,
            daily_cap=settings.global_daily_run_cap,
            max_attempts=settings.job_max_attempts,
            budgets=server_budgets(settings),
        )

    with start_span(
        "request.validate",
        topic_chars=len(body.topic or ""),
        has_idempotency_key=bool((idempotency_key or "").strip()),
    ) as span:
        job, reused = call_db(_start)
        span.set(reused=bool(reused), run_id=job.id)
    if not reused:
        wake_consumer(request)
    return JSONResponse(status_code=202, content=public_job(job, reused=reused))


@router.get("/research-runs/{run_id}")
def get_run(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    identity = call_db(lambda: identity_from_token(session, token))
    job = call_db(lambda: get_owned_job(session, run_id, identity.id))
    usage = call_db(lambda: run_usage(session, job.id))
    return {**public_job(job), "usage": usage}


@router.get("/research-runs/{run_id}/events")
def get_events(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
    after: int = 0,
) -> dict[str, object]:
    identity = call_db(lambda: identity_from_token(session, token))
    rows = call_db(lambda: list_events(session, run_id, identity.id, after=after))
    return {"run_id": run_id, "events": [public_event(row) for row in rows]}


@router.post("/research-runs/{run_id}/cancel")
def cancel(
    run_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    identity = call_db(lambda: identity_from_token(session, token))
    job = call_db(lambda: cancel_run(session, run_id, identity.id))
    wake_consumer(request)
    return public_job(job)


def _review(
    action: str, run_id: str, body: ReviewRequest, request: Request, session: Session, token: str
) -> dict[str, object]:
    identity = call_db(lambda: identity_from_token(session, token))
    job = call_db(lambda: request_review(session, run_id, identity.id, action, body.comments))
    wake_consumer(request)
    return public_job(job)


@router.post("/research-runs/{run_id}/approve")
def approve(
    run_id: str,
    body: ReviewRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    return _review("approve", run_id, body, request, session, token)


@router.post("/research-runs/{run_id}/revise")
def revise(
    run_id: str,
    body: ReviewRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    return _review("revise", run_id, body, request, session, token)


@router.post("/research-runs/{run_id}/reject")
def reject(
    run_id: str,
    body: ReviewRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    return _review("reject", run_id, body, request, session, token)
