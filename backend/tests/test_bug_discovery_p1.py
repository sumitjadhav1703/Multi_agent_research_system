"""Discovery tests for known P1 bugs.

Each test asserts the correct behavior and is marked expectedFailure so the
suite stays green while the bug is still present. Do not weaken these
assertions to match the current product code.
"""
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
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select

from backend.app.core.config import clear_settings_cache
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.db.models import DemoEntitlement, GuestIdentity, JobEvent, ResearchJob
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.executor import ExecutionResult, _run_graph
from backend.app.jobs.persist import finalize_job
from backend.app.jobs.quota import identity_from_token, issue_guest_identity, start_run
from backend.app.jobs.retention import purge_expired_data
from backend.app.jobs.timeutil import add_days, add_seconds, utc_now
from backend.app.jobs.turnstile import StaticTurnstileVerifier
from backend.tests.helpers import mock_settings

BUDGETS = {
    "max_subquestions": 3,
    "max_parallel_workers": 2,
    "max_sources": 6,
    "max_search_calls": 4,
    "max_model_calls": 12,
    "max_wall_clock_seconds": 180,
}


class BugDiscoveryP1Tests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self.settings = mock_settings()
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "bug-discovery-p1.sqlite3"
        self.engine = make_engine(f"sqlite:///{self.path}")
        apply_migrations(self.engine)
        self.factory = make_session_factory(self.engine)
        self.verifier = StaticTurnstileVerifier({"ok"})

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def test_wall_clock_keeps_review_required(self) -> None:
        """BI-P1-1: an interrupted review must stay review_required.

        Current _run_graph overwrites that status to expired when monotonic
        time across runner.start exceeds max_wall_clock_seconds.
        """

        class _Paused:
            def start(self, topic: str, *, owner_id: str, run_id: str) -> SimpleNamespace:
                del topic, owner_id, run_id
                return SimpleNamespace(
                    interrupted=True,
                    approval_status="awaiting_review",
                    events=[],
                    state={"approval_status": "awaiting_review", "events": []},
                )

        readings = iter((0.0, 10.0))

        def _monotonic() -> float:
            try:
                return next(readings)
            except StopIteration:
                return 10.0

        with patch("backend.app.jobs.executor.time.monotonic", _monotonic):
            result = _run_graph(
                runner=_Paused(),
                job_id="wall-clock-review",
                topic="Widget latency",
                owner_id="owner",
                resume_action=None,
                resume_comments="",
                attempts=1,
                max_wall_clock_seconds=1,
            )
        self.assertEqual(result.status, "review_required")

    def test_review_resumed_is_stored_when_event_id_collides(self) -> None:
        """BI-P1-2: review.resumed must be stored even if event_id is reused.

        Current _append_new_events skips any event whose event_id was already
        seen, so a later review.resumed with the same id as review.awaiting
        never lands in job_events.
        """
        now = utc_now()
        job_id = "11111111-1111-1111-1111-111111111111"
        self._seed_running_job(job_id, owner_id="event-owner", now=now)
        finalize_job(
            self.factory,
            job_id,
            ExecutionResult(
                status="review_required",
                provider_work_started=True,
                approval_status="awaiting_review",
                events=[{"event_id": 5, "type": "review.awaiting", "payload": {}}],
            ),
            worker_id="worker-test",
        )
        with self.factory() as session:
            stored = session.get(ResearchJob, job_id)
            self.assertIsNotNone(stored)
            assert stored is not None
            stored.status = "running"
            stored.lease_owner = "worker-test"
            stored.finished_at = None
            session.commit()
        finalize_job(
            self.factory,
            job_id,
            ExecutionResult(
                status="completed",
                provider_work_started=True,
                approval_status="approved",
                events=[{"event_id": 5, "type": "review.resumed", "payload": {"action": "approve"}}],
            ),
            worker_id="worker-test",
        )
        with self.factory() as session:
            types = set(session.scalars(select(JobEvent.event_type).where(JobEvent.job_id == job_id)).all())
        self.assertIn("review.resumed", types)

    def test_retention_keeps_non_terminal_review_job(self) -> None:
        """BI-P1-4: purge must not delete a non-terminal review_required job.

        Current purge_expired_data deletes every job older than the cutoff.
        DemoEntitlement.job_id is not a foreign key, so the consumed
        entitlement is left behind after the job row disappears. Desired
        behavior is to keep the job.
        """
        now = utc_now()
        created_at = add_days(now, -3)
        job_id = str(uuid.uuid4())
        owner_id = f"owner-{job_id[:8]}"
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id=owner_id,
                    created_at=created_at,
                    expires_at=add_days(now, 14),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id=owner_id,
                    topic="retention review fixture",
                    status="review_required",
                    idempotency_key=f"key-{job_id}",
                    thread_id=job_id,
                    attempts=1,
                    max_attempts=3,
                    cancel_requested=0,
                    provider_work_started=1,
                    approval_status="awaiting_review",
                    config_version="m3-queue-v1",
                    budget_json=json.dumps({"max_model_calls": 12}),
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            session.flush()
            session.add(
                DemoEntitlement(
                    identity_id=owner_id,
                    status="consumed",
                    job_id=job_id,
                    consumed_at=created_at,
                )
            )
            session.commit()

        # Created long ago but touched recently (a fresh review cycle): kept.
        with self.factory() as session:
            session.execute(
                ResearchJob.__table__.update().where(ResearchJob.id == job_id).values(updated_at=now)
            )
            session.commit()
        with self.factory() as session:
            purge_expired_data(session, retention_days=2, now=now, batch_size=50)
            session.commit()

        with self.factory() as session:
            self.assertIsNotNone(session.get(ResearchJob, job_id))

    def test_review_required_does_not_consume_active_slot(self) -> None:
        """BI-P1-5: review_required must not count toward the global active cap."""
        first = self._issue("ok")
        second = self._issue("ok")
        job, reused = self._start(first, "Widget latency", "slot-1", max_active=5, daily_cap=10)
        self.assertFalse(reused)
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            self.assertIsNotNone(stored)
            assert stored is not None
            stored.status = "review_required"
            session.commit()
        try:
            started, _reused_again = self._start(
                second, "Another topic", "slot-2", max_active=1, daily_cap=10
            )
        except JobServiceError as exc:
            self.fail(f"second start should succeed while the first run awaits review, got {exc.code}")
        self.assertEqual(started.status, "queued")

    def _issue(self, turnstile_token: str) -> str:
        with self.factory() as session:
            return issue_guest_identity(
                session,
                verifier=self.verifier,
                turnstile_token=turnstile_token,
                remote_ip=None,
                ttl_hours=24,
            )

    def _start(
        self,
        token: str,
        topic: str,
        key: str,
        *,
        max_active: int,
        daily_cap: int,
    ) -> tuple[ResearchJob, bool]:
        with self.factory() as session:
            owner = identity_from_token(session, token)
            return start_run(
                session,
                identity_id=owner.id,
                topic=topic,
                idempotency_key=key,
                max_active=max_active,
                daily_cap=daily_cap,
                max_attempts=3,
                budgets=BUDGETS,
            )

    def _seed_running_job(self, job_id: str, *, owner_id: str, now: str) -> None:
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id=owner_id,
                    created_at=now,
                    expires_at=add_seconds(now, 3600),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(
                DemoEntitlement(
                    identity_id=owner_id,
                    status="consumed",
                    job_id=job_id,
                    consumed_at=now,
                )
            )
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id=owner_id,
                    topic="Widget latency",
                    status="running",
                    idempotency_key=f"key-{job_id}",
                    thread_id=job_id,
                    lease_owner="worker-test",
                    attempts=1,
                    max_attempts=3,
                    cancel_requested=0,
                    provider_work_started=1,
                    config_version="m3-queue-v1",
                    budget_json="{}",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()


if __name__ == "__main__":
    unittest.main()
