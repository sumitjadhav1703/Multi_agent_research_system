"""Data retention purge for demo Neon storage limits."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = ""
os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
os.environ["TURNSTILE_SECRET_KEY"] = ""

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import func, select

from backend.app.core.config import clear_settings_cache
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.db.models import (
    DemoEntitlement,
    EvidencePassage,
    GuestIdentity,
    IdempotencyKey,
    JobEvent,
    QuotaGuard,
    ResearchClaim,
    ResearchJob,
    ResearchReport,
    ResearchSource,
    UsageLedger,
)
from backend.app.jobs.retention import purge_expired_data, retention_due
from backend.app.jobs.timeutil import add_days, add_seconds, utc_now
from backend.tests.helpers import mock_settings


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "retention.sqlite3"
        self.engine = make_engine(f"sqlite:///{self.path}")
        apply_migrations(self.engine)
        self.factory = make_session_factory(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def test_purges_jobs_older_than_two_days_and_keeps_recent(self) -> None:
        now = utc_now()
        old_id = self._seed_job(created_at=add_days(now, -3), with_artifacts=True)
        recent_id = self._seed_job(created_at=add_days(now, -1), with_artifacts=True)

        with self.factory() as session:
            stats = purge_expired_data(session, retention_days=2, now=now, batch_size=50)
            session.commit()

        self.assertEqual(stats.jobs_deleted, 1)
        self.assertEqual(stats.identities_deleted, 1)
        with self.factory() as session:
            remaining_jobs = {row.id for row in session.scalars(select(ResearchJob))}
            self.assertEqual(remaining_jobs, {recent_id})
            self.assertEqual(session.scalar(select(func.count()).select_from(JobEvent)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(ResearchSource)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(EvidencePassage)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(ResearchClaim)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(ResearchReport)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(UsageLedger)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(IdempotencyKey)), 1)
            self.assertIsNone(session.get(ResearchJob, old_id))
            # Singleton quota row must survive forever.
            self.assertEqual(session.scalar(select(func.count()).select_from(QuotaGuard)), 1)

    def test_batch_size_limits_jobs_per_pass(self) -> None:
        now = utc_now()
        for offset in (5, 4, 3):
            self._seed_job(created_at=add_days(now, -offset), with_artifacts=False)

        with self.factory() as session:
            stats = purge_expired_data(session, retention_days=2, now=now, batch_size=2)
            session.commit()

        self.assertEqual(stats.jobs_deleted, 2)
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ResearchJob)), 1)

        with self.factory() as session:
            stats = purge_expired_data(session, retention_days=2, now=now, batch_size=2)
            session.commit()
        self.assertEqual(stats.jobs_deleted, 1)

    def test_expired_orphan_identity_is_removed(self) -> None:
        now = utc_now()
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id="orphan-expired",
                    created_at=add_days(now, -1),
                    expires_at=add_seconds(now, -60),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(
                DemoEntitlement(
                    identity_id="orphan-expired",
                    status="available",
                    job_id=None,
                    consumed_at=None,
                    refunded_at=None,
                    refund_reason=None,
                )
            )
            session.commit()

        with self.factory() as session:
            stats = purge_expired_data(session, retention_days=2, now=now)
            session.commit()

        self.assertEqual(stats.identities_deleted, 1)
        with self.factory() as session:
            self.assertIsNone(session.get(GuestIdentity, "orphan-expired"))
            self.assertIsNone(session.get(DemoEntitlement, "orphan-expired"))

    def test_retention_due_respects_interval(self) -> None:
        now = utc_now()
        self.assertTrue(retention_due(last_run_at=None, interval_seconds=3600, now=now))
        self.assertFalse(
            retention_due(last_run_at=now, interval_seconds=3600, now=add_seconds(now, 10))
        )
        self.assertTrue(
            retention_due(last_run_at=now, interval_seconds=3600, now=add_seconds(now, 3600))
        )

    def test_settings_reject_zero_retention_days(self) -> None:
        with self.assertRaises(ValueError):
            mock_settings(DATA_RETENTION_DAYS="0")

    def _seed_job(self, *, created_at: str, with_artifacts: bool) -> str:
        job_id = str(uuid.uuid4())
        owner_id = f"owner-{job_id[:8]}"
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id=owner_id,
                    created_at=created_at,
                    expires_at=add_days(created_at, 14),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id=owner_id,
                    topic="retention fixture",
                    status="completed",
                    idempotency_key=f"key-{job_id}",
                    thread_id=job_id,
                    attempts=1,
                    max_attempts=3,
                    cancel_requested=0,
                    provider_work_started=1,
                    config_version="test",
                    budget_json=json.dumps({"max_model_calls": 12}),
                    created_at=created_at,
                    updated_at=created_at,
                    finished_at=created_at,
                )
            )
            session.flush()
            session.add(
                DemoEntitlement(
                    identity_id=owner_id,
                    status="consumed",
                    job_id=job_id,
                    consumed_at=created_at,
                    refunded_at=None,
                    refund_reason=None,
                )
            )
            if with_artifacts:
                session.add(
                    JobEvent(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        sequence_id=1,
                        event_type="run.completed",
                        payload="{}",
                        created_at=created_at,
                    )
                )
                session.add(
                    ResearchSource(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        source_key="s1",
                        canonical_url="https://example.com/a",
                        url="https://example.com/a",
                        domain="example.com",
                        title="Example",
                        content_hash="abc",
                        extraction_method="html",
                        retrieved_at=created_at,
                        excerpt="hello",
                    )
                )
                session.add(
                    EvidencePassage(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        evidence_key="e1",
                        source_key="s1",
                        subquestion_id="q1",
                        quote="hello",
                    )
                )
                session.add(
                    ResearchClaim(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        claim_key="c1",
                        claim_text="hello exists",
                        status="supported",
                        verification_reason="overlap",
                        evidence_ids_json=json.dumps(["e1"]),
                    )
                )
                session.add(
                    ResearchReport(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        version=1,
                        markdown="# Report",
                        approval_state="approved",
                        created_at=created_at,
                    )
                )
                session.add(
                    UsageLedger(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        identity_id=owner_id,
                        provider="mock",
                        model="mock/free-model",
                        llm_calls=1,
                        prompt_tokens=10,
                        completion_tokens=5,
                        total_tokens=15,
                        estimated_cost_usd=None,
                        search_calls=1,
                        created_at=created_at,
                    )
                )
                session.add(
                    IdempotencyKey(
                        id=str(uuid.uuid4()),
                        identity_id=owner_id,
                        idempotency_key=f"key-{job_id}",
                        request_hash="deadbeef",
                        job_id=job_id,
                        created_at=created_at,
                    )
                )
            session.commit()
        return job_id


if __name__ == "__main__":
    unittest.main()
