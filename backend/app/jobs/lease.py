"""Job leases. Postgres uses FOR UPDATE SKIP LOCKED. SQLite uses one conditional UPDATE.

SQLite's writer lock blocks the second waiter instead of skipping the locked row.
That is safe for the single-process tests and is not the production lease.
"""
from __future__ import annotations

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from backend.app.db.models import ResearchJob
from backend.app.jobs.quota import refund_entitlement
from backend.app.jobs.timeutil import add_seconds, utc_now

_POSTGRES_LEASE = """
WITH candidate AS (
    SELECT id
    FROM research_jobs
    WHERE status IN ('queued', 'running')
      AND cancel_requested = 0
      AND attempts < max_attempts
      AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
      AND (lease_expires_at IS NULL OR lease_expires_at < :now)
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE research_jobs
SET lease_owner = :worker,
    lease_expires_at = :expires,
    heartbeat_at = :now,
    attempts = attempts + 1,
    status = 'running',
    started_at = COALESCE(started_at, :now),
    updated_at = :now
WHERE id IN (SELECT id FROM candidate)
RETURNING id
"""

_SQLITE_LEASE = """
UPDATE research_jobs
SET lease_owner = :worker,
    lease_expires_at = :expires,
    heartbeat_at = :now,
    attempts = attempts + 1,
    status = 'running',
    started_at = COALESCE(started_at, :now),
    updated_at = :now
WHERE id = (
    SELECT id FROM research_jobs
    WHERE status IN ('queued', 'running')
      AND cancel_requested = 0
      AND attempts < max_attempts
      AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
      AND (lease_expires_at IS NULL OR lease_expires_at < :now)
    ORDER BY created_at
    LIMIT 1
)
RETURNING id
"""


def lease_next(session: Session, *, worker_id: str, now: str, lease_seconds: int) -> str | None:
    dialect = session.get_bind().dialect.name
    statement = _POSTGRES_LEASE if dialect == "postgresql" else _SQLITE_LEASE
    row = session.execute(
        text(statement),
        {
            "worker": worker_id,
            "now": now,
            "expires": add_seconds(now, lease_seconds),
        },
    ).first()
    if row is None:
        return None
    return str(row[0])


def heartbeat(session: Session, *, job_id: str, worker_id: str, now: str, lease_seconds: int) -> bool:
    result = session.execute(
        update(ResearchJob)
        .where(ResearchJob.id == job_id)
        .where(ResearchJob.lease_owner == worker_id)
        .where(ResearchJob.status == "running")
        .values(
            heartbeat_at=now,
            lease_expires_at=add_seconds(now, lease_seconds),
            updated_at=now,
        )
    )
    return result.rowcount == 1


def recover_expired_leases(session: Session, *, now: str | None = None) -> list[str]:
    """Make expired running leases leasable again. Does not call a provider."""
    current = now or utc_now()
    rows = session.scalars(
        select(ResearchJob).where(
            ResearchJob.status == "running",
            ResearchJob.lease_expires_at.is_not(None),
            ResearchJob.lease_expires_at < current,
        )
    ).all()
    recovered: list[str] = []
    for job in rows:
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = current
        if job.cancel_requested:
            job.status = "cancelled"
            job.finished_at = current
            job.error_code = "cancelled"
        elif job.attempts >= job.max_attempts:
            job.status = "failed"
            job.finished_at = current
            job.error_code = "attempts_exhausted"
            job.error_detail = "lease_expired"
            if not job.provider_work_started:
                refund_entitlement(session, job, now=current, reason="lease_expired_before_provider")
        else:
            job.status = "queued"
            recovered.append(job.id)
    return recovered
