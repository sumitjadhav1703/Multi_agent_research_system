"""Delete demo research data older than the configured retention window.

Runs inside the API process (startup + periodic queue-consumer tick). This is
not a separate paid worker and not FastAPI BackgroundTasks as the sole owner.

Deletes jobs older than the cutoff and their child rows, then orphan guest
identities that have no remaining jobs and whose token has already expired
(`expires_at < now`). Unexpired guest rows are kept so a Turnstile-issued
bearer remains usable until GUEST_TOKEN_TTL_HOURS elapses. quota_guard is
never deleted. LangGraph checkpoint rows are best-effort removed by
thread_id on Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, delete, or_, select, text
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DemoEntitlement,
    EvidencePassage,
    GuestIdentity,
    IdempotencyKey,
    JobEvent,
    ResearchClaim,
    ResearchJob,
    ResearchReport,
    ResearchSource,
    UsageLedger,
)
from backend.app.jobs.timeutil import add_days, utc_now
from backend.app.observability import emit

# Child tables that reference research_jobs.id (delete before the job row).
_JOB_CHILD_MODELS = (
    JobEvent,
    ResearchSource,
    EvidencePassage,
    ResearchClaim,
    ResearchReport,
    UsageLedger,
    IdempotencyKey,
)

_CHECKPOINT_TABLES = (
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
)


@dataclass(frozen=True)
class PurgeStats:
    jobs_deleted: int = 0
    identities_deleted: int = 0
    checkpoint_threads_attempted: int = 0

    @property
    def total_deleted(self) -> int:
        return self.jobs_deleted + self.identities_deleted


def purge_expired_data(
    session: Session,
    *,
    retention_days: int = 2,
    now: str | None = None,
    batch_size: int = 100,
) -> PurgeStats:
    """Remove app rows older than retention_days. Caller commits or rolls back."""
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1.")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    clock = now or utc_now()
    cutoff = add_days(clock, -retention_days)

    job_ids, thread_ids = _select_old_jobs(session, cutoff=cutoff, batch_size=batch_size)
    if job_ids:
        for model in _JOB_CHILD_MODELS:
            session.execute(delete(model).where(model.job_id.in_(job_ids)))
        session.execute(delete(ResearchJob).where(ResearchJob.id.in_(job_ids)))

    identity_ids = _select_orphan_identities(session, now=clock, cutoff=cutoff, batch_size=batch_size)
    if identity_ids:
        session.execute(delete(DemoEntitlement).where(DemoEntitlement.identity_id.in_(identity_ids)))
        session.execute(delete(GuestIdentity).where(GuestIdentity.id.in_(identity_ids)))

    checkpoint_threads = 0
    if thread_ids:
        checkpoint_threads = _purge_checkpoints(session, thread_ids)

    return PurgeStats(
        jobs_deleted=len(job_ids),
        identities_deleted=len(identity_ids),
        checkpoint_threads_attempted=checkpoint_threads,
    )


def run_retention_pass(
    session: Session,
    *,
    retention_days: int,
    now: str | None = None,
    batch_size: int = 100,
) -> PurgeStats:
    """Purge and emit a structured log line. Caller still owns commit."""
    stats = purge_expired_data(
        session,
        retention_days=retention_days,
        now=now,
        batch_size=batch_size,
    )
    if stats.total_deleted or stats.checkpoint_threads_attempted:
        emit(
            "retention.purged",
            {
                "jobs_deleted": stats.jobs_deleted,
                "identities_deleted": stats.identities_deleted,
                "checkpoint_threads_attempted": stats.checkpoint_threads_attempted,
                "retention_days": retention_days,
            },
        )
    return stats


def _select_old_jobs(
    session: Session, *, cutoff: str, batch_size: int
) -> tuple[list[str], list[str]]:
    rows = session.execute(
        select(ResearchJob.id, ResearchJob.thread_id)
        .where(ResearchJob.created_at < cutoff)
        .order_by(ResearchJob.created_at.asc())
        .limit(batch_size)
    ).all()
    job_ids = [row[0] for row in rows]
    thread_ids = [row[1] for row in rows if row[1]]
    return job_ids, thread_ids


def _select_orphan_identities(
    session: Session, *, now: str, cutoff: str, batch_size: int
) -> list[str]:
    """Delete only expired orphan guests.

    A visitor may verify Turnstile and wait days before starting a run. Their
    bearer stays valid until expires_at (GUEST_TOKEN_TTL_HOURS). Rows with a
    null expires_at are treated as corrupt and removed only after the job
    retention cutoff so they cannot linger forever.
    """
    job_owners = select(ResearchJob.owner_id).distinct()
    rows = session.scalars(
        select(GuestIdentity.id)
        .where(
            GuestIdentity.id.not_in(job_owners),
            or_(
                and_(
                    GuestIdentity.expires_at.is_not(None),
                    GuestIdentity.expires_at < now,
                ),
                and_(
                    GuestIdentity.expires_at.is_(None),
                    GuestIdentity.created_at < cutoff,
                ),
            ),
        )
        .order_by(GuestIdentity.created_at.asc())
        .limit(batch_size)
    ).all()
    return list(rows)


def _purge_checkpoints(session: Session, thread_ids: list[str]) -> int:
    """Best-effort LangGraph checkpoint cleanup. No-op when tables are absent."""
    bind = session.bind
    if bind is None or bind.dialect.name != "postgresql":
        return 0
    existing = {
        name
        for (name,) in session.execute(
            text(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = current_schema()
                  AND tablename = ANY(:names)
                """
            ),
            {"names": list(_CHECKPOINT_TABLES)},
        )
    }
    if not existing:
        return 0
    for table in _CHECKPOINT_TABLES:
        if table not in existing:
            continue
        session.execute(
            text(f"DELETE FROM {table} WHERE thread_id = ANY(:thread_ids)"),
            {"thread_ids": thread_ids},
        )
    return len(thread_ids)


def retention_due(*, last_run_at: str | None, interval_seconds: int, now: str | None = None) -> bool:
    """True when no prior run or the interval has elapsed."""
    if interval_seconds < 1:
        return True
    if not last_run_at:
        return True
    clock = now or utc_now()
    return _seconds_elapsed(last_run_at, clock) >= interval_seconds


def _seconds_elapsed(earlier: str, later: str) -> float:
    from datetime import datetime, timezone

    start = datetime.fromisoformat(earlier)
    end = datetime.fromisoformat(later)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (end - start).total_seconds()
