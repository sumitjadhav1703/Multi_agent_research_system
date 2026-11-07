"""Guest issuance, one-use entitlement, idempotent start, cancel, and review."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DemoEntitlement,
    GuestIdentity,
    IdempotencyKey,
    JobEvent,
    QuotaGuard,
    ResearchJob,
)
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.timeutil import add_seconds, utc_day, utc_now
from backend.app.jobs.turnstile import TurnstileVerifier
from backend.app.observability import start_span

ACTIVE_STATUSES = ("queued", "running", "review_required")
TERMINAL_STATUSES = ("completed", "failed", "cancelled", "expired")
CONFIG_VERSION = "m3-queue-v1"

_RESERVE_GLOBAL = """
UPDATE quota_guard
SET daily_window = :today,
    daily_count = CASE WHEN daily_window = :today THEN daily_count + 1 ELSE 1 END
WHERE id = 1
  AND (
    SELECT COUNT(*) FROM research_jobs
    WHERE status IN ('queued', 'running', 'review_required')
  ) < :max_active
  AND (
    CASE WHEN daily_window = :today THEN daily_count ELSE 0 END
  ) < :daily_cap
"""


def hash_guest_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _topic_hash(topic: str) -> str:
    return hashlib.sha256(topic.strip().encode("utf-8")).hexdigest()


def issue_guest_identity(
    session: Session,
    *,
    verifier: TurnstileVerifier,
    turnstile_token: str,
    remote_ip: str | None,
    ttl_hours: int,
) -> str:
    if not verifier.verify(turnstile_token, remote_ip):
        raise JobServiceError(403, "turnstile_failed", "Human verification failed.")
    now = utc_now()
    raw = secrets.token_urlsafe(32)
    digest = hash_guest_token(raw)
    session.add(
        GuestIdentity(
            id=digest,
            created_at=now,
            expires_at=add_seconds(now, ttl_hours * 3600),
            turnstile_verified=1,
        )
    )
    session.flush()
    session.add(DemoEntitlement(identity_id=digest, status="available"))
    session.commit()
    return raw


def identity_from_token(session: Session, raw: str, *, now: str | None = None) -> GuestIdentity:
    if not raw or len(raw) < 20 or len(raw) > 200 or any(char.isspace() for char in raw):
        raise JobServiceError(401, "unauthorized", "Guest token is missing or invalid.")
    row = session.get(GuestIdentity, hash_guest_token(raw))
    current = now or utc_now()
    # A missing expiry is not an immortal token. Issuance always sets expires_at.
    if row is None or not row.expires_at or row.expires_at < current:
        raise JobServiceError(401, "unauthorized", "Guest token is missing or invalid.")
    return row


def start_run(
    session: Session,
    *,
    identity_id: str,
    topic: str,
    idempotency_key: str,
    max_active: int,
    daily_cap: int,
    max_attempts: int,
    budgets: dict[str, int],
) -> tuple[ResearchJob, bool]:
    with start_span("quota.check", identity_id=identity_id, topic_chars=len(topic or "")) as span:
        try:
            job, reused = _start_run_body(
                session,
                identity_id=identity_id,
                topic=topic,
                idempotency_key=idempotency_key,
                max_active=max_active,
                daily_cap=daily_cap,
                max_attempts=max_attempts,
                budgets=budgets,
            )
        except JobServiceError as exc:
            span.set(quota_decision="denied", **{"error.code": exc.code})
            raise
        span.set(quota_decision="reused" if reused else "allowed", run_id=job.id)
        return job, reused


def _start_run_body(
    session: Session,
    *,
    identity_id: str,
    topic: str,
    idempotency_key: str,
    max_active: int,
    daily_cap: int,
    max_attempts: int,
    budgets: dict[str, int],
) -> tuple[ResearchJob, bool]:
    cleaned = topic.strip()
    if not cleaned or len(cleaned) > 500:
        raise JobServiceError(422, "invalid_topic", "Topic must be 1 to 500 characters.")
    key = idempotency_key.strip()
    if not key or len(key) > 200 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise JobServiceError(400, "missing_idempotency_key", "Idempotency-Key is required.")

    digest = _topic_hash(cleaned)
    existing = _idempotency_row(session, identity_id, key)
    if existing is not None:
        return _reuse_or_conflict(session, existing, digest), True

    entitlement = session.get(DemoEntitlement, identity_id)
    if entitlement is None:
        raise JobServiceError(403, "entitlement_missing", "This guest identity cannot start a run.")
    if entitlement.status == "consumed":
        raise JobServiceError(
            409,
            "quota_consumed",
            "This guest identity has already used its one research run.",
        )

    now = utc_now()
    job_id = str(uuid.uuid4())
    consumed = session.execute(
        update(DemoEntitlement)
        .where(DemoEntitlement.identity_id == identity_id)
        .where(DemoEntitlement.status.in_(("available", "refunded")))
        .values(status="consumed", job_id=job_id, consumed_at=now, refunded_at=None, refund_reason=None)
    )
    if consumed.rowcount != 1:
        session.rollback()
        raced = _idempotency_row(session, identity_id, key)
        if raced is not None:
            return _reuse_or_conflict(session, raced, digest), True
        raise JobServiceError(
            409,
            "quota_consumed",
            "This guest identity has already used its one research run.",
        )

    reserved = session.execute(
        text(_RESERVE_GLOBAL),
        {"today": utc_day(now), "max_active": max_active, "daily_cap": daily_cap},
    )
    if reserved.rowcount != 1:
        session.rollback()
        raise _global_limit_error(session, max_active=max_active, daily_cap=daily_cap, now=now)

    job = ResearchJob(
        id=job_id,
        owner_id=identity_id,
        topic=cleaned,
        status="queued",
        idempotency_key=key,
        thread_id=job_id,
        attempts=0,
        max_attempts=max_attempts,
        cancel_requested=0,
        provider_work_started=0,
        config_version=CONFIG_VERSION,
        budget_json=json.dumps(budgets, sort_keys=True),
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.flush()
    session.add(
        IdempotencyKey(
            id=str(uuid.uuid4()),
            identity_id=identity_id,
            idempotency_key=key,
            request_hash=digest,
            job_id=job_id,
            created_at=now,
        )
    )
    _append_event(session, job_id, "run.queued", {"status": "queued"}, now)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = _idempotency_row(session, identity_id, key)
        if raced is not None:
            return _reuse_or_conflict(session, raced, digest), True
        raise JobServiceError(409, "quota_conflict", "Another start won the race for this identity.") from None
    return job, False


_REFUND_DAILY = """
UPDATE quota_guard
SET daily_count = daily_count - 1
WHERE id = 1
  AND daily_window = :today
  AND daily_count > 0
"""


def release_daily_slot(session: Session, now: str) -> bool:
    """Return one daily slot in this transaction. A zero count stays zero."""
    result = session.execute(text(_REFUND_DAILY), {"today": utc_day(now)})
    return result.rowcount == 1


def refund_entitlement(session: Session, job: ResearchJob, *, now: str, reason: str) -> bool:
    """Refund only when provider work never started. Daily cap is returned too.

    The entitlement row and the daily decrement commit together. The decrement
    is one conditional UPDATE, so two refunds cannot both subtract the last slot.
    """
    if job.provider_work_started:
        return False
    entitlement = session.get(DemoEntitlement, job.owner_id)
    if entitlement is None or entitlement.status != "consumed" or entitlement.job_id != job.id:
        return False
    entitlement.status = "refunded"
    entitlement.job_id = None
    entitlement.refunded_at = now
    entitlement.refund_reason = reason[:120]
    release_daily_slot(session, now)
    return True


def get_owned_job(session: Session, job_id: str, owner_id: str) -> ResearchJob:
    job = session.get(ResearchJob, job_id)
    if job is None or job.owner_id != owner_id:
        raise JobServiceError(404, "run_not_found", "Run not found.")
    return job


def cancel_run(session: Session, job_id: str, owner_id: str) -> ResearchJob:
    job = get_owned_job(session, job_id, owner_id)
    if job.status in TERMINAL_STATUSES:
        return job
    now = utc_now()
    job.cancel_requested = 1
    job.updated_at = now
    if job.status in {"queued", "review_required"} and not job.lease_owner:
        job.status = "cancelled"
        job.finished_at = now
        job.error_code = "cancelled"
        _append_event(session, job.id, "run.cancelled", {"status": "cancelled"}, now)
    session.commit()
    return job


def request_review(
    session: Session,
    job_id: str,
    owner_id: str,
    action: str,
    comments: str,
) -> ResearchJob:
    if action not in {"approve", "revise", "reject"}:
        raise JobServiceError(422, "invalid_review", "Review action is not allowed.")
    job = get_owned_job(session, job_id, owner_id)
    if job.status != "review_required":
        raise JobServiceError(409, "not_awaiting_review", "This run is not waiting for review.")
    now = utc_now()
    job.resume_action = action
    job.resume_comments = comments.strip()[:2000]
    job.status = "queued"
    job.lease_owner = None
    job.lease_expires_at = None
    job.updated_at = now
    _append_event(session, job.id, "review.requested", {"action": action}, now)
    session.commit()
    return job


def list_events(session: Session, job_id: str, owner_id: str, *, after: int) -> list[JobEvent]:
    get_owned_job(session, job_id, owner_id)
    return list(
        session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.sequence_id > after)
            .order_by(JobEvent.sequence_id)
        ).all()
    )


def usage_snapshot(
    session: Session,
    identity_id: str,
    *,
    max_active: int,
    daily_cap: int,
    budgets: dict[str, int],
) -> dict[str, object]:
    entitlement = session.get(DemoEntitlement, identity_id)
    guard = session.get(QuotaGuard, 1)
    now = utc_now()
    active = session.scalar(
        select(func.count()).select_from(ResearchJob).where(ResearchJob.status.in_(ACTIVE_STATUSES))
    )
    runs = session.scalars(
        select(ResearchJob).where(ResearchJob.owner_id == identity_id).order_by(ResearchJob.created_at)
    ).all()
    daily = 0
    if guard is not None and guard.daily_window == utc_day(now):
        daily = guard.daily_count
    return {
        "identity_scope": "guest",
        "one_use_consumed": bool(entitlement and entitlement.status == "consumed"),
        "one_use_refunded": bool(entitlement and entitlement.status == "refunded"),
        "run_ids": [job.id for job in runs],
        "global_max_active_runs": max_active,
        "global_active_runs": int(active or 0),
        "global_daily_cap": daily_cap,
        "global_daily_starts": int(daily),
        "limits": budgets,
        "estimated_cost_usd": None,
        "note": "One run per issued guest token, not one verified run per person.",
    }


def _idempotency_row(session: Session, identity_id: str, key: str) -> IdempotencyKey | None:
    return session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.identity_id == identity_id,
            IdempotencyKey.idempotency_key == key,
        )
    )


def _reuse_or_conflict(session: Session, row: IdempotencyKey, digest: str) -> ResearchJob:
    if row.request_hash != digest:
        raise JobServiceError(
            409,
            "idempotency_conflict",
            "Idempotency-Key was already used for a different request.",
        )
    job = session.get(ResearchJob, row.job_id)
    if job is None:
        raise JobServiceError(409, "idempotency_conflict", "Idempotency-Key does not match a stored run.")
    return job


def _global_limit_error(session: Session, *, max_active: int, daily_cap: int, now: str) -> JobServiceError:
    active = session.scalar(
        select(func.count()).select_from(ResearchJob).where(ResearchJob.status.in_(ACTIVE_STATUSES))
    )
    guard = session.get(QuotaGuard, 1)
    daily = guard.daily_count if guard is not None and guard.daily_window == utc_day(now) else 0
    if int(active or 0) >= max_active:
        return JobServiceError(
            429,
            "global_active_limit",
            "The demo already has the maximum number of active runs.",
        )
    if int(daily) >= daily_cap:
        return JobServiceError(429, "global_daily_limit", "The demo has reached its daily run cap.")
    return JobServiceError(429, "global_limit", "The demo cannot start another run right now.")


def _append_event(session: Session, job_id: str, event_type: str, payload: dict[str, object], now: str) -> None:
    current = session.scalar(select(func.max(JobEvent.sequence_id)).where(JobEvent.job_id == job_id)) or 0
    session.add(
        JobEvent(
            id=str(uuid.uuid4()),
            job_id=job_id,
            sequence_id=int(current) + 1,
            event_type=event_type,
            payload=json.dumps(payload, sort_keys=True),
            created_at=now,
        )
    )
