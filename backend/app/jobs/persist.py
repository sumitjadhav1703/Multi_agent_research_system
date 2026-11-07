"""Persist graph output and finish a leased job. Artifact rows are replaced; events append."""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    EvidencePassage,
    JobEvent,
    ResearchClaim,
    ResearchReport,
    ResearchSource,
    UsageLedger,
)
from backend.app.jobs.executor import ExecutionResult
from backend.app.jobs.quota import TERMINAL_STATUSES, refund_entitlement
from backend.app.jobs.timeutil import add_seconds, utc_now
from backend.app.observability import start_span


def finalize_job(
    session_factory: Callable[[], Session],
    job_id: str,
    result: ExecutionResult,
    *,
    worker_id: str,
) -> None:
    with start_span("report.persist", job_id=job_id) as span:
        _finalize_owned(session_factory, job_id, result, worker_id=worker_id, span=span)


def _finalize_owned(
    session_factory: Callable[[], Session],
    job_id: str,
    result: ExecutionResult,
    *,
    worker_id: str,
    span: Any,
) -> None:
    session = session_factory()
    try:
        from backend.app.db.models import ResearchJob

        job = session.get(ResearchJob, job_id)
        if job is None or job.lease_owner != worker_id:
            # A missing lease means recovery already released the row. Writing
            # here would let a stale worker finish a job it no longer owns.
            span.set(outcome="skipped")
            return
        now = utc_now()
        if result.provider_work_started:
            job.provider_work_started = 1
        _replace_artifacts(session, job.id, job.owner_id, result, now)
        _append_new_events(session, job.id, result.events, now)
        if result.retryable and result.status == "failed" and job.attempts < job.max_attempts:
            job.status = "queued"
            job.next_attempt_at = add_seconds(now, min(30, 2 ** max(job.attempts, 1)))
            job.error_code = result.error_code
            job.error_detail = _safe(result.error_detail)
        else:
            job.status = result.status if result.status in _KNOWN else "failed"
            job.approval_status = result.approval_status
            job.stop_reason = result.stop_reason
            job.error_code = result.error_code
            job.error_detail = _safe(result.error_detail)
            job.resume_action = None
            job.resume_comments = None
            if job.status in TERMINAL_STATUSES or job.status == "expired":
                job.finished_at = now
            if job.status == "failed" and not job.provider_work_started:
                refund_entitlement(session, job, now=now, reason="failed_before_provider")
            _append_new_events(
                session,
                job.id,
                [{"type": f"run.{job.status}", "payload": {"status": job.status}}],
                now,
            )
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = now
        session.commit()
        span.set(
            outcome="saved",
            status=job.status,
            report_saved=bool(result.report_markdown),
            source_count=len(result.sources),
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_KNOWN = {"queued", "running", "review_required", "completed", "failed", "cancelled", "expired"}


def _replace_artifacts(session: Session, job_id: str, owner_id: str, result: ExecutionResult, now: str) -> None:
    for model in (EvidencePassage, ResearchClaim, ResearchSource, ResearchReport):
        session.execute(delete(model).where(model.job_id == job_id))
    seen_urls: set[str] = set()
    seen_keys: set[str] = set()
    for source in result.sources:
        key = str(source.get("source_id") or "")[:80]
        url = str(source.get("canonical_url") or source.get("url") or key)[:1000]
        if not key or key in seen_keys or url in seen_urls:
            continue
        seen_keys.add(key)
        seen_urls.add(url)
        session.add(
            ResearchSource(
                id=str(uuid.uuid4()),
                job_id=job_id,
                source_key=key,
                canonical_url=url,
                url=str(source.get("url") or url)[:1000],
                domain=str(source.get("domain") or "")[:255],
                title=str(source.get("title") or "")[:300],
                content_hash=str(source.get("content_hash") or "")[:64],
                extraction_method=str(source.get("extraction_method") or "failed")[:40],
                retrieved_at=(str(source.get("retrieved_at"))[:40] if source.get("retrieved_at") else None),
                excerpt=(str(source.get("excerpt"))[:4000] if source.get("excerpt") else None),
            )
        )
    for passage in result.passages:
        key = str(passage.get("evidence_id") or "")[:80]
        if not key:
            continue
        session.add(
            EvidencePassage(
                id=str(uuid.uuid4()),
                job_id=job_id,
                evidence_key=key,
                source_key=str(passage.get("source_id") or "")[:80],
                subquestion_id=(str(passage.get("subquestion_id"))[:80] if passage.get("subquestion_id") else None),
                quote=str(passage.get("quote") or "")[:4000],
            )
        )
    for claim in result.claims:
        key = str(claim.get("claim_id") or "")[:80]
        if not key:
            continue
        session.add(
            ResearchClaim(
                id=str(uuid.uuid4()),
                job_id=job_id,
                claim_key=key,
                claim_text=str(claim.get("text") or "")[:4000],
                status=str(claim.get("status") or "insufficient")[:32],
                verification_reason=(str(claim.get("verification_reason"))[:2000] if claim.get("verification_reason") else None),
                evidence_ids_json=json.dumps(list(claim.get("evidence_ids") or []))[:4000],
            )
        )
    if result.report_markdown:
        session.add(
            ResearchReport(
                id=str(uuid.uuid4()),
                job_id=job_id,
                version=1,
                markdown=result.report_markdown[:20000],
                approval_state=(result.approval_status or "draft")[:40],
                created_at=now,
            )
        )
    usage = result.usage or {}
    if usage:
        session.add(
            UsageLedger(
                id=str(uuid.uuid4()),
                job_id=job_id,
                identity_id=owner_id,
                provider=None,
                model=None,
                llm_calls=_optional_int(usage.get("llm_calls")),
                prompt_tokens=_optional_int(usage.get("prompt_tokens")),
                completion_tokens=_optional_int(usage.get("completion_tokens")),
                total_tokens=_optional_int(usage.get("total_tokens")),
                estimated_cost_usd=None,
                search_calls=_optional_int(usage.get("search_calls")),
                created_at=now,
            )
        )


def _append_new_events(session: Session, job_id: str, events: list[dict], now: str) -> None:
    existing = list(session.scalars(select(JobEvent).where(JobEvent.job_id == job_id)).all())
    seen_ids: set[int] = set()
    seen_types: set[str] = set()
    current = 0
    for row in existing:
        current = max(current, row.sequence_id)
        seen_types.add(row.event_type)
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get("event_id"), int):
            seen_ids.add(payload["event_id"])
    for event in events:
        event_type = str(event.get("type") or "run.event")[:80]
        event_id = event.get("event_id")
        if isinstance(event_id, int) and event_id in seen_ids:
            continue
        if event_type.startswith("run.") and event_type in seen_types and not isinstance(event_id, int):
            continue
        current += 1
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if isinstance(event_id, int):
            payload = {**payload, "event_id": event_id}
        session.add(
            JobEvent(
                id=str(uuid.uuid4()),
                job_id=job_id,
                sequence_id=current,
                event_type=event_type,
                payload=json.dumps(payload, sort_keys=True, default=str)[:8000],
                created_at=now,
            )
        )
        seen_types.add(event_type)
        if isinstance(event_id, int):
            seen_ids.add(event_id)


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _safe(value: str | None) -> str | None:
    if not value:
        return None
    return value[:300]
