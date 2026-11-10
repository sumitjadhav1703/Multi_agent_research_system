"""ORM mapping for the versioned SQL migration. Column names match 0001."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class GuestIdentity(Base):
    __tablename__ = "guest_identities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(40))
    turnstile_verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DemoEntitlement(Base):
    __tablename__ = "demo_entitlements"

    identity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("guest_identities.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(36))
    consumed_at: Mapped[str | None] = mapped_column(String(40))
    refunded_at: Mapped[str | None] = mapped_column(String(40))
    refund_reason: Mapped[str | None] = mapped_column(String(120))


class QuotaGuard(Base):
    __tablename__ = "quota_guard"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_window: Mapped[str] = mapped_column(String(10), nullable=False)
    daily_count: Mapped[int] = mapped_column(Integer, nullable=False)


class ResearchJob(Base):
    __tablename__ = "research_jobs"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_research_jobs_owner_idempotency"),
        Index("ix_research_jobs_owner_created", "owner_id", "created_at"),
        Index("ix_research_jobs_status_lease", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("guest_identities.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[str | None] = mapped_column(String(40))
    heartbeat_at: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[str | None] = mapped_column(String(40))
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_work_started: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_detail: Mapped[str | None] = mapped_column(String(300))
    approval_status: Mapped[str | None] = mapped_column(String(40))
    stop_reason: Mapped[str | None] = mapped_column(String(80))
    resume_action: Mapped[str | None] = mapped_column(String(16))
    resume_comments: Mapped[str | None] = mapped_column(String(2000))
    config_version: Mapped[str] = mapped_column(String(40), nullable=False)
    budget_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("identity_id", "idempotency_key", name="uq_idempotency_identity_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(String(64), ForeignKey("guest_identities.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_jobs.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence_id", name="uq_job_events_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_jobs.id"), nullable=False)
    sequence_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class ResearchSource(Base):
    __tablename__ = "research_sources"
    __table_args__ = (
        UniqueConstraint("job_id", "source_key", name="uq_sources_job_key"),
        UniqueConstraint("job_id", "canonical_url", name="uq_sources_job_url"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_jobs.id"), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    retrieved_at: Mapped[str | None] = mapped_column(String(40))
    excerpt: Mapped[str | None] = mapped_column(Text)


class EvidencePassage(Base):
    __tablename__ = "evidence_passages"
    __table_args__ = (UniqueConstraint("job_id", "evidence_key", name="uq_passages_job_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_jobs.id"), nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(80), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    subquestion_id: Mapped[str | None] = mapped_column(String(80))
    quote: Mapped[str] = mapped_column(Text, nullable=False)


class ResearchClaim(Base):
    __tablename__ = "research_claims"
    __table_args__ = (UniqueConstraint("job_id", "claim_key", name="uq_claims_job_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_jobs.id"), nullable=False)
    claim_key: Mapped[str] = mapped_column(String(80), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_reason: Mapped[str | None] = mapped_column(Text)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)


class ResearchReport(Base):
    __tablename__ = "research_reports"
    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_reports_job_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_jobs.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    approval_state: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class UsageLedger(Base):
    __tablename__ = "usage_ledger"
    __table_args__ = (
        Index("ix_usage_ledger_job", "job_id"),
        Index("ix_usage_ledger_identity", "identity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("research_jobs.id"), nullable=False)
    identity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(160))
    llm_calls: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[str | None] = mapped_column(String(32))
    search_calls: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
