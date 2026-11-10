"""Milestone 3 quotas, leases, ownership, and fail-closed database behavior."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = ""
os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
os.environ["TURNSTILE_SECRET_KEY"] = ""

import tempfile
import threading
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import clear_settings_cache
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.db.models import (
    DemoEntitlement,
    GuestIdentity,
    JobEvent,
    QuotaGuard,
    ResearchJob,
    ResearchSource,
    UsageLedger,
)
from backend.app.jobs.consumer import QueueConsumer, process_one
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.executor import ExecutionResult, GraphJobExecutor, _budget
from backend.app.jobs.lease import recover_expired_leases
from backend.app.jobs.persist import finalize_job
from backend.app.jobs.quota import (
    cancel_run,
    hash_guest_token,
    identity_from_token,
    issue_guest_identity,
    refund_entitlement,
    release_daily_slot,
    request_review,
    start_run,
)
from backend.app.jobs.timeutil import add_seconds, utc_day, utc_now
from backend.app.jobs.turnstile import HttpTurnstileVerifier, StaticTurnstileVerifier
from backend.app.main import create_app
from backend.tests.graph_fakes import (
    LAB_HITS,
    LAB_PAGES,
    FixtureRetrieval,
    client_for,
    scripted_behavior,
    success_roles,
)
from backend.tests.helpers import mock_settings

BUDGETS = {
    "max_subquestions": 3,
    "max_parallel_workers": 2,
    "max_sources": 6,
    "max_search_calls": 4,
    "max_model_calls": 12,
    "max_wall_clock_seconds": 180,
}


class QuotaJobTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "m3.sqlite3"
        self.engine = make_engine(f"sqlite:///{self.path}")
        apply_migrations(self.engine)
        self.factory = make_session_factory(self.engine)
        self.verifier = StaticTurnstileVerifier({"ok"})

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def test_migrations_are_idempotent(self) -> None:
        apply_migrations(self.engine)
        with self.factory() as session:
            versions = [row[0] for row in session.execute(text("SELECT version FROM schema_migrations"))]
        self.assertEqual(versions, ["0001_identity_jobs_quota.sql", "0002_index_cleanup.sql"])

    def test_guest_token_is_hashed_and_turnstile_is_required(self) -> None:
        with self.assertRaises(JobServiceError) as caught:
            self._issue("nope")
        self.assertEqual(caught.exception.code, "turnstile_failed")
        token = self._issue("ok")
        with self.factory() as session:
            row = session.scalars(select(GuestIdentity)).one()
            self.assertEqual(row.id, hash_guest_token(token))
            self.assertNotIn(token, row.id)
            self.assertEqual(session.scalar(select(func.count()).select_from(GuestIdentity)), 1)

    def test_same_key_replay_returns_one_run(self) -> None:
        token = self._issue("ok")
        first, reused = self._start(token, "Widget latency", "same-key")
        second, reused_again = self._start(token, "Widget latency", "same-key")
        self.assertFalse(reused)
        self.assertTrue(reused_again)
        self.assertEqual(first.id, second.id)
        self.assertEqual(self._job_count(), 1)

    def test_simultaneous_starts_create_one_run(self) -> None:
        token = self._issue("ok")
        barrier = threading.Barrier(2)
        found: list[str] = []
        codes: list[str] = []

        def _go(key: str) -> None:
            barrier.wait(timeout=5)
            try:
                job, _reused = self._start(token, "Widget latency", key)
                found.append(job.id)
            except JobServiceError as exc:
                codes.append(exc.code)

        threads = [threading.Thread(target=_go, args=("race-key",)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(self._job_count(), 1)
        self.assertEqual(len(set(found)), 1)
        self.assertEqual(codes, [])

        fresh = self._issue("ok")
        barrier = threading.Barrier(2)
        raced: list[str] = []
        raced_codes: list[str] = []

        def _other(key: str) -> None:
            barrier.wait(timeout=5)
            try:
                job, _reused = self._start(fresh, "Widget latency", key, max_active=5, daily_cap=10)
                raced.append(job.id)
            except JobServiceError as exc:
                raced_codes.append(exc.code)

        threads = [threading.Thread(target=_other, args=(key,)) for key in ("other-a", "other-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(len(raced), 1)
        self.assertEqual(raced_codes, ["quota_consumed"])

    def test_used_identity_cannot_start_again_but_can_read(self) -> None:
        token = self._issue("ok")
        job, _reused = self._start(token, "Widget latency", "once")
        with self.assertRaises(JobServiceError) as caught:
            self._start(token, "Another topic", "twice")
        self.assertEqual(caught.exception.code, "quota_consumed")
        with self.factory() as session:
            loaded = identity_from_token(session, token)
            visible = session.get(ResearchJob, job.id)
            self.assertEqual(visible.owner_id, loaded.id)

    def test_global_active_and_daily_caps(self) -> None:
        first = self._issue("ok")
        second = self._issue("ok")
        self._start(first, "Widget latency", "cap-1")
        with self.assertRaises(JobServiceError) as active:
            self._start(second, "Widget latency", "cap-2", max_active=1, daily_cap=3)
        self.assertEqual(active.exception.code, "global_active_limit")

    def test_global_daily_cap(self) -> None:
        first = self._issue("ok")
        second = self._issue("ok")
        self._start(first, "Daily one", "day-1", max_active=5, daily_cap=1)
        with self.assertRaises(JobServiceError) as daily:
            self._start(second, "Daily two", "day-2", max_active=5, daily_cap=1)
        self.assertEqual(daily.exception.code, "global_daily_limit")

    def test_cancel_consumes_entitlement_before_provider_work(self) -> None:
        token = self._issue("ok")
        job, _reused = self._start(token, "Widget latency", "cancel-me")
        from backend.app.jobs.quota import cancel_run

        with self.factory() as session:
            owner = identity_from_token(session, token)
            cancelled = cancel_run(session, job.id, owner.id)
            self.assertEqual(cancelled.status, "cancelled")
            entitlement = session.get(DemoEntitlement, owner.id)
            self.assertEqual(entitlement.status, "consumed")
        with self.assertRaises(JobServiceError) as caught:
            self._start(token, "Widget latency", "cancel-again")
        self.assertEqual(caught.exception.code, "quota_consumed")

    def test_same_key_different_topic_conflicts_and_keys_are_per_owner(self) -> None:
        token = self._issue("ok")
        job, reused = self._start(token, "Widget latency", "same-key")
        self.assertFalse(reused)
        with self.assertRaises(JobServiceError) as caught:
            self._start(token, "A different topic", "same-key")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.code, "idempotency_conflict")
        self.assertEqual(self._job_count(), 1)
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            self.assertEqual(stored.topic, "Widget latency")

        first = self._issue("ok")
        second = self._issue("ok")
        left, left_reused = self._start(first, "Topic A", "shared-key", max_active=5, daily_cap=10)
        right, right_reused = self._start(second, "Topic B", "shared-key", max_active=5, daily_cap=10)
        self.assertFalse(left_reused)
        self.assertFalse(right_reused)
        self.assertNotEqual(left.id, right.id)
        self.assertEqual(left.topic, "Topic A")
        self.assertEqual(right.topic, "Topic B")

    def test_cancel_after_provider_work_keeps_the_entitlement(self) -> None:
        token = self._issue("ok")
        job, _reused = self._start(token, "Widget latency", "cancel-after-work")
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            stored.status = "running"
            stored.provider_work_started = 1
            stored.lease_owner = "worker-test"
            session.commit()
            owner = identity_from_token(session, token)
            flagged = cancel_run(session, job.id, owner.id)
            self.assertEqual(flagged.cancel_requested, 1)
            self.assertEqual(flagged.status, "running")
            self.assertEqual(session.get(DemoEntitlement, owner.id).status, "consumed")

        finalize_job(
            self.factory,
            job.id,
            ExecutionResult(status="completed", provider_work_started=True, approval_status="approved"),
            worker_id="worker-test",
        )
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            owner = identity_from_token(session, token)
            entitlement = session.get(DemoEntitlement, owner.id)
            self.assertEqual(stored.status, "cancelled")
            self.assertEqual(stored.error_code, "cancelled")
            self.assertEqual(stored.provider_work_started, 1)
            self.assertEqual(entitlement.status, "consumed")
            self.assertEqual(entitlement.job_id, job.id)
            self.assertFalse(refund_entitlement(session, stored, now=utc_now(), reason="cancel_after_work"))
            session.commit()
            self.assertEqual(session.get(QuotaGuard, 1).daily_count, 1)
            self.assertEqual(session.get(DemoEntitlement, owner.id).status, "consumed")
        with self.assertRaises(JobServiceError) as caught:
            self._start(token, "Another topic", "after-worked-cancel")
        self.assertEqual(caught.exception.code, "quota_consumed")

    def test_failure_after_provider_work_does_not_refund(self) -> None:
        token = self._issue("ok")
        job, _reused = self._start(token, "Widget latency", "fail-after-work")

        class _FailAfter:
            def execute(self, _factory: object, job_id: str) -> ExecutionResult:
                self.job_id = job_id
                return ExecutionResult(
                    status="failed",
                    provider_work_started=True,
                    error_code="provider_error",
                    error_detail="provider_error",
                )

        worker = _FailAfter()
        processed = process_one(
            session_factory=self.factory,
            executor=worker,
            worker_id="worker-test",
            lease_seconds=30,
            heartbeat_seconds=30,
        )
        self.assertEqual(processed, job.id)
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            owner = identity_from_token(session, token)
            self.assertEqual(stored.status, "failed")
            self.assertEqual(stored.provider_work_started, 1)
            self.assertEqual(session.get(DemoEntitlement, owner.id).status, "consumed")
            self.assertEqual(session.get(QuotaGuard, 1).daily_count, 1)
            self.assertFalse(refund_entitlement(session, stored, now=utc_now(), reason="failed_after_provider"))
            session.commit()
            self.assertEqual(session.get(QuotaGuard, 1).daily_count, 1)
        with self.assertRaises(JobServiceError) as caught:
            self._start(token, "Widget latency", "fail-after-again")
        self.assertEqual(caught.exception.code, "quota_consumed")

    def test_failure_before_provider_refunds_one_use(self) -> None:
        token = self._issue("ok")
        job, _reused = self._start(token, "Widget latency", "refund-me")

        class _Fail:
            def execute(self, _factory, job_id: str) -> ExecutionResult:
                self.job_id = job_id
                return ExecutionResult(
                    status="failed",
                    provider_work_started=False,
                    error_code="database_unavailable",
                    error_detail="database_unavailable",
                )

        process_one(
            session_factory=self.factory,
            executor=_Fail(),
            worker_id="worker-test",
            lease_seconds=30,
            heartbeat_seconds=30,
        )
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            owner = identity_from_token(session, token)
            entitlement = session.get(DemoEntitlement, owner.id)
            self.assertEqual(stored.status, "failed")
            self.assertEqual(stored.provider_work_started, 0)
            self.assertEqual(entitlement.status, "refunded")
            self.assertEqual(session.get(QuotaGuard, 1).daily_count, 0)
            self.assertFalse(refund_entitlement(session, stored, now=utc_now(), reason="again"))
            session.commit()
            self.assertEqual(session.get(QuotaGuard, 1).daily_count, 0)
        again, _reused = self._start(token, "Widget latency", "refund-retry")
        self.assertNotEqual(again.id, job.id)

    def test_expired_lease_is_recovered_and_events_survive_reopen(self) -> None:
        now = utc_now()
        job_id = "11111111-1111-1111-1111-111111111111"
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id="owner-hash",
                    created_at=now,
                    expires_at=add_seconds(now, 3600),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(DemoEntitlement(identity_id="owner-hash", status="consumed", job_id=job_id, consumed_at=now))
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id="owner-hash",
                    topic="Widget latency",
                    status="running",
                    idempotency_key="lease-key",
                    thread_id=job_id,
                    lease_owner="dead-worker",
                    lease_expires_at=add_seconds(now, -90),
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
            recovered = recover_expired_leases(session, now=now)
            session.commit()
            self.assertEqual(recovered, [job_id])
            self.assertEqual(session.get(ResearchJob, job_id).status, "queued")

        class _Done:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def execute(self, _factory, leased_id: str) -> ExecutionResult:
                self.calls.append(leased_id)
                return ExecutionResult(
                    status="completed",
                    provider_work_started=True,
                    approval_status="approved",
                    events=[{"type": "worker.done", "event_id": 7, "payload": {"ok": True}}],
                    usage={"llm_calls": 2, "prompt_tokens": None, "estimated_cost_usd": 0},
                )

        worker = _Done()
        process_one(
            session_factory=self.factory,
            executor=worker,
            worker_id="worker-test",
            lease_seconds=30,
            heartbeat_seconds=30,
        )
        self.assertEqual(worker.calls, [job_id])
        self.engine.dispose()
        reopened = make_engine(f"sqlite:///{self.path}")
        try:
            factory = make_session_factory(reopened)
            with factory() as session:
                stored = session.get(ResearchJob, job_id)
                self.assertEqual(stored.status, "completed")
                ledger = session.scalars(select(UsageLedger).where(UsageLedger.job_id == job_id)).one()
                self.assertIsNone(ledger.estimated_cost_usd)
                self.assertIsNone(ledger.prompt_tokens)
                types = [row.event_type for row in session.scalars(select(JobEvent).where(JobEvent.job_id == job_id))]
                self.assertIn("worker.done", types)
        finally:
            reopened.dispose()

    def test_parallel_daily_refunds_stop_at_zero(self) -> None:
        now = utc_now()
        with self.factory() as session:
            guard = session.get(QuotaGuard, 1)
            guard.daily_window = utc_day(now)
            guard.daily_count = 2
            session.commit()
        barrier = threading.Barrier(4)
        errors: list[BaseException] = []

        def _hit() -> None:
            try:
                barrier.wait(timeout=5)
                with self.factory() as session:
                    release_daily_slot(session, now)
                    session.commit()
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_hit) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(errors, [])
        with self.factory() as session:
            self.assertEqual(session.get(QuotaGuard, 1).daily_count, 0)

    def test_null_expiry_and_foreign_lease_are_rejected(self) -> None:
        raw = "n" * 32
        now = utc_now()
        job_id = "22222222-2222-2222-2222-222222222222"
        with self.factory() as session:
            session.add(
                GuestIdentity(id=hash_guest_token(raw), created_at=now, expires_at=None, turnstile_verified=1)
            )
            session.commit()
            with self.assertRaises(JobServiceError) as caught:
                identity_from_token(session, raw)
        self.assertEqual(caught.exception.status_code, 401)

        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id="lease-owner",
                    created_at=now,
                    expires_at=add_seconds(now, 3600),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(DemoEntitlement(identity_id="lease-owner", status="consumed", job_id=job_id, consumed_at=now))
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id="lease-owner",
                    topic="Widget latency",
                    status="running",
                    idempotency_key="lease-final",
                    thread_id=job_id,
                    lease_owner=None,
                    attempts=1,
                    max_attempts=3,
                    cancel_requested=0,
                    provider_work_started=0,
                    config_version="m3-queue-v1",
                    budget_json="{}",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        done = ExecutionResult(status="completed", provider_work_started=True, approval_status="approved")
        finalize_job(self.factory, job_id, done, worker_id="worker-test")
        with self.factory() as session:
            self.assertEqual(session.get(ResearchJob, job_id).status, "running")
            session.get(ResearchJob, job_id).lease_owner = "other-worker"
            session.commit()
        finalize_job(self.factory, job_id, done, worker_id="worker-test")
        with self.factory() as session:
            stored = session.get(ResearchJob, job_id)
            self.assertEqual(stored.status, "running")
            stored.lease_owner = "worker-test"
            session.commit()
        finalize_job(self.factory, job_id, done, worker_id="worker-test")
        with self.factory() as session:
            self.assertEqual(session.get(ResearchJob, job_id).status, "completed")

    def test_second_queue_consumer_is_refused(self) -> None:
        class _Idle:
            def execute(self, _factory, job_id: str) -> ExecutionResult:
                raise AssertionError(job_id)

        first = QueueConsumer(
            session_factory=self.factory,
            executor=_Idle(),
            worker_id="consumer-a",
            poll_seconds=0.05,
        )
        second = QueueConsumer(
            session_factory=self.factory,
            executor=_Idle(),
            worker_id="consumer-b",
            poll_seconds=0.05,
        )
        first.start()
        try:
            with self.assertRaises(RuntimeError):
                second.start()
        finally:
            first.stop()
            second.stop()

    def test_database_failure_does_not_call_the_provider(self) -> None:
        class _Spy:
            def __init__(self) -> None:
                self.calls = 0

            def complete(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("provider called")

        class _Boom:
            def get(self, *_args, **_kwargs):
                raise SQLAlchemyError("postgresql://user:secret@db.example/researchmind")

            def commit(self) -> None:
                raise SQLAlchemyError("postgresql://user:secret@db.example/researchmind")

            def rollback(self) -> None:
                return None

            def close(self) -> None:
                return None

        spy = _Spy()
        result = GraphJobExecutor(mock_settings(), model_client=spy, retrieval=object()).execute(
            lambda: _Boom(),
            "job-1",
        )
        self.assertEqual(result.error_code, "database_unavailable")
        self.assertFalse(result.provider_work_started)
        self.assertEqual(spy.calls, 0)

    def test_graph_executor_persists_evidence_and_resumes(self) -> None:
        token = self._issue("ok")
        job, _reused = self._start(token, "Widget latency", "graph-key")
        client, _router = client_for(scripted_behavior(success_roles(1)))
        from backend.app.graph.checkpointer import build_checkpointer

        executor = GraphJobExecutor(
            mock_settings(),
            checkpointer=build_checkpointer("memory"),
            model_client=client,
            retrieval=FixtureRetrieval(LAB_HITS, LAB_PAGES),
        )
        process_one(
            session_factory=self.factory,
            executor=executor,
            worker_id="graph-worker",
            lease_seconds=60,
            heartbeat_seconds=30,
        )
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            self.assertEqual(stored.status, "review_required")
            self.assertEqual(stored.provider_work_started, 1)
            sources = session.scalars(select(ResearchSource).where(ResearchSource.job_id == job.id)).all()
            self.assertGreaterEqual(len(sources), 1)
            owner = identity_from_token(session, token)
            request_review(session, job.id, owner.id, "approve", "Ship it.")
        process_one(
            session_factory=self.factory,
            executor=executor,
            worker_id="graph-worker",
            lease_seconds=60,
            heartbeat_seconds=30,
        )
        with self.factory() as session:
            stored = session.get(ResearchJob, job.id)
            self.assertEqual(stored.status, "completed")
            self.assertEqual(stored.approval_status, "approved")

    def test_explicit_zero_model_budget_is_preserved(self) -> None:
        budget = _budget('{"max_model_calls":0}')
        self.assertEqual(budget["max_model_calls"], 0)
        self.assertEqual(budget["max_wall_clock_seconds"], 180)
        self.assertEqual(_budget('{"max_wall_clock_seconds":0}')["max_wall_clock_seconds"], 0)
        self.assertEqual(_budget("{}")["max_model_calls"], 12)
        self.assertEqual(_budget('{"max_model_calls":null}')["max_model_calls"], 12)

    def test_second_finalize_replaces_usage_ledger(self) -> None:
        now = utc_now()
        job_id = "33333333-3333-3333-3333-333333333333"
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id="ledger-owner",
                    created_at=now,
                    expires_at=add_seconds(now, 3600),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(DemoEntitlement(identity_id="ledger-owner", status="consumed", job_id=job_id, consumed_at=now))
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id="ledger-owner",
                    topic="Widget latency",
                    status="running",
                    idempotency_key="ledger-key",
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
        first = ExecutionResult(
            status="review_required",
            provider_work_started=True,
            approval_status="pending",
            usage={
                "llm_calls": 2,
                "prompt_tokens": 5,
                "completion_tokens": 1,
                "total_tokens": 6,
                "search_calls": 1,
            },
        )
        finalize_job(self.factory, job_id, first, worker_id="worker-test")
        with self.factory() as session:
            stored = session.get(ResearchJob, job_id)
            self.assertEqual(stored.status, "review_required")
            stored.status = "running"
            stored.lease_owner = "worker-test"
            stored.finished_at = None
            session.commit()
        second = ExecutionResult(
            status="completed",
            provider_work_started=True,
            approval_status="approved",
            usage={
                "llm_calls": 3,
                "prompt_tokens": 8,
                "completion_tokens": 4,
                "total_tokens": 12,
                "search_calls": 2,
            },
        )
        finalize_job(self.factory, job_id, second, worker_id="worker-test")
        with self.factory() as session:
            rows = session.scalars(select(UsageLedger).where(UsageLedger.job_id == job_id)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].llm_calls, 3)
            self.assertEqual(rows[0].prompt_tokens, 8)
            self.assertEqual(rows[0].completion_tokens, 4)
            self.assertEqual(rows[0].total_tokens, 12)
            self.assertEqual(rows[0].search_calls, 2)
            self.assertEqual(session.get(ResearchJob, job_id).status, "completed")

    def test_empty_usage_preserves_prior_ledger(self) -> None:
        now = utc_now()
        job_id = "55555555-5555-5555-5555-555555555555"
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id="usage-keep-owner",
                    created_at=now,
                    expires_at=add_seconds(now, 3600),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(
                DemoEntitlement(
                    identity_id="usage-keep-owner",
                    status="consumed",
                    job_id=job_id,
                    consumed_at=now,
                )
            )
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id="usage-keep-owner",
                    topic="Widget latency",
                    status="running",
                    idempotency_key="usage-keep",
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
        finalize_job(
            self.factory,
            job_id,
            ExecutionResult(
                status="review_required",
                provider_work_started=True,
                approval_status="pending",
                usage={
                    "llm_calls": 4,
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "search_calls": 1,
                },
            ),
            worker_id="worker-test",
        )
        with self.factory() as session:
            stored = session.get(ResearchJob, job_id)
            stored.status = "running"
            stored.lease_owner = "worker-test"
            stored.finished_at = None
            session.commit()
        finalize_job(
            self.factory,
            job_id,
            ExecutionResult(status="failed", provider_work_started=True, error_code="graph_error", usage={}),
            worker_id="worker-test",
        )
        with self.factory() as session:
            rows = session.scalars(select(UsageLedger).where(UsageLedger.job_id == job_id)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].llm_calls, 4)
            self.assertEqual(rows[0].total_tokens, 12)
            self.assertEqual(session.get(ResearchJob, job_id).status, "failed")

    def test_zero_wall_clock_skips_graph_start(self) -> None:
        from backend.app.jobs.executor import _run_graph

        class _Boom:
            def start(self, *args, **kwargs):
                raise AssertionError("start must not run when wall clock is zero")

            def resume(self, *args, **kwargs):
                raise AssertionError("resume must not run when wall clock is zero")

            def peek(self, *args, **kwargs):
                raise AssertionError("peek must not run when wall clock is zero")

        result = _run_graph(
            runner=_Boom(),
            job_id="zero-clock",
            topic="Widget latency",
            owner_id="owner",
            resume_action=None,
            resume_comments="",
            attempts=1,
            max_wall_clock_seconds=0,
        )
        self.assertEqual(result.status, "expired")
        self.assertEqual(result.error_code, "wall_clock")
        self.assertFalse(result.provider_work_started)

    def test_refresh_cancel_flag_overrides_stale_memory(self) -> None:
        from sqlalchemy import update

        import backend.app.jobs.persist as persist_mod

        now = utc_now()
        job_id = "66666666-6666-6666-6666-666666666666"
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id="cancel-reread-owner",
                    created_at=now,
                    expires_at=add_seconds(now, 3600),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(
                DemoEntitlement(
                    identity_id="cancel-reread-owner",
                    status="consumed",
                    job_id=job_id,
                    consumed_at=now,
                )
            )
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id="cancel-reread-owner",
                    topic="Widget latency",
                    status="running",
                    idempotency_key="cancel-reread",
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
        with self.factory() as session:
            session.execute(update(ResearchJob).where(ResearchJob.id == job_id).values(cancel_requested=1))
            session.commit()
        with self.factory() as session:
            job = session.get(ResearchJob, job_id)
            job.cancel_requested = 0  # stale in-memory value after a concurrent cancel
            persist_mod._refresh_cancel_flag(session, job)
            self.assertEqual(job.cancel_requested, 1)
        finalize_job(
            self.factory,
            job_id,
            ExecutionResult(status="completed", provider_work_started=True, approval_status="approved"),
            worker_id="worker-test",
        )
        with self.factory() as session:
            stored = session.get(ResearchJob, job_id)
            self.assertEqual(stored.status, "cancelled")
            self.assertEqual(stored.error_code, "cancelled")

    def test_cancel_after_start_is_persisted(self) -> None:
        now = utc_now()
        job_id = "44444444-4444-4444-4444-444444444444"
        with self.factory() as session:
            session.add(
                GuestIdentity(
                    id="cancel-owner",
                    created_at=now,
                    expires_at=add_seconds(now, 3600),
                    turnstile_verified=1,
                )
            )
            session.flush()
            session.add(DemoEntitlement(identity_id="cancel-owner", status="consumed", job_id=job_id, consumed_at=now))
            session.add(
                ResearchJob(
                    id=job_id,
                    owner_id="cancel-owner",
                    topic="Widget latency",
                    status="running",
                    idempotency_key="cancel-after-start",
                    thread_id=job_id,
                    lease_owner="worker-test",
                    attempts=1,
                    max_attempts=3,
                    cancel_requested=0,
                    provider_work_started=0,
                    config_version="m3-queue-v1",
                    budget_json="{}",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        factory = self.factory

        class _Outcome:
            interrupted = False
            approval_status = "approved"
            events = [{"type": "worker.done", "event_id": 3, "payload": {"ok": True}}]
            state = {
                "approval_status": "approved",
                "stop_reason": "answered",
                "usage": {
                    "llm_calls": 4,
                    "prompt_tokens": 9,
                    "completion_tokens": 3,
                    "total_tokens": 12,
                    "search_calls": 1,
                },
                "events": [],
                "sources": [],
                "passages": [],
                "claims": [],
            }

        class _Runner:
            def start(self, topic: str, *, owner_id: str, run_id: str) -> _Outcome:
                with factory() as session:
                    job = session.get(ResearchJob, run_id)
                    if job is None:
                        raise AssertionError(run_id)
                    job.cancel_requested = 1
                    session.commit()
                return _Outcome()

        class _Executor(GraphJobExecutor):
            def _runner(self, max_model_calls: int) -> _Runner:
                return _Runner()

        result = _Executor(mock_settings()).execute(factory, job_id)
        # finalize_job (not the executor) turns a late cancel into "cancelled".
        self.assertTrue(result.provider_work_started)
        self.assertEqual(result.usage.get("llm_calls"), 4)
        self.assertEqual(result.events[0]["type"], "worker.done")
        finalize_job(factory, job_id, result, worker_id="worker-test")
        with factory() as session:
            stored = session.get(ResearchJob, job_id)
            self.assertEqual(stored.status, "cancelled")
            self.assertEqual(stored.error_code, "cancelled")
            self.assertEqual(stored.provider_work_started, 1)

        with factory() as session:
            stored = session.get(ResearchJob, job_id)
            stored.status = "running"
            stored.lease_owner = "worker-test"
            stored.finished_at = None
            stored.cancel_requested = 1
            stored.error_code = None
            session.commit()
        raced = ExecutionResult(
            status="completed",
            provider_work_started=True,
            approval_status="approved",
            usage={"llm_calls": 1, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "search_calls": 0},
        )
        finalize_job(factory, job_id, raced, worker_id="worker-test")
        with factory() as session:
            stored = session.get(ResearchJob, job_id)
            self.assertEqual(stored.status, "cancelled")
            self.assertEqual(stored.error_code, "cancelled")

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
        max_active: int = 5,
        daily_cap: int = 10,
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

    def _job_count(self) -> int:
        with self.factory() as session:
            return int(session.scalar(select(func.count()).select_from(ResearchJob)) or 0)


class RunsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "api.sqlite3"
        self.engine = make_engine(f"sqlite:///{path}")
        apply_migrations(self.engine)
        self.factory = make_session_factory(self.engine)
        self.app = create_app()
        self.app.state.session_factory = self.factory
        self.app.state.turnstile_verifier = StaticTurnstileVerifier({"ok"})
        self.app.state.consumer_enabled = False
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def test_create_get_events_usage_cancel_and_ownership(self) -> None:
        guest = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        self.assertEqual(guest.status_code, 201)
        self.assertEqual(guest.headers["cache-control"], "no-store")
        token = guest.json()["guest_token"]
        self.assertNotIn(token, guest.text.replace(token, "", 1))
        other = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        other_token = other.json()["guest_token"]

        created = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Widget latency", "max_model_calls": 9999},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "api-key"},
        )
        self.assertEqual(created.status_code, 202)
        body = created.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["budgets"]["max_model_calls"], 12)
        self.assertFalse(body["reused"])
        run_id = body["run_id"]

        replay = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Widget latency"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "api-key"},
        )
        self.assertEqual(replay.status_code, 202)
        self.assertTrue(replay.json()["reused"])
        self.assertEqual(replay.json()["run_id"], run_id)

        denied = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Another topic"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "api-key-2"},
        )
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["code"], "quota_consumed")

        fetched = self.client.get(
            f"/api/v1/research-runs/{run_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(fetched.status_code, 200)
        hidden = self.client.get(
            f"/api/v1/research-runs/{run_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        self.assertEqual(hidden.status_code, 404)
        hidden_events = self.client.get(
            f"/api/v1/research-runs/{run_id}/events",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        self.assertEqual(hidden_events.status_code, 404)
        events = self.client.get(
            f"/api/v1/research-runs/{run_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(events.status_code, 200)
        self.assertIn("run.queued", [item["type"] for item in events.json()["events"]])

        usage = self.client.get("/api/v1/me/usage", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(usage.status_code, 200)
        self.assertTrue(usage.json()["one_use_consumed"])
        self.assertEqual(usage.json()["global_max_active_runs"], 1)
        self.assertIsNone(usage.json()["estimated_cost_usd"])
        self.assertIsNone(usage.json()["llm_calls"])
        self.assertNotIn(token, usage.text)

        ready = self.client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["database"], "ok")

        cancelled = self.client.post(
            f"/api/v1/research-runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        stolen = self.client.post(
            f"/api/v1/research-runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        self.assertEqual(stolen.status_code, 404)

    def test_cross_owner_review_is_hidden_and_usage_stays_separate(self) -> None:
        guest = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        token = guest.json()["guest_token"]
        other = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        other_token = other.json()["guest_token"]
        created = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Private transit notes"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "owner-key"},
        )
        self.assertEqual(created.status_code, 202)
        run_id = created.json()["run_id"]

        for action in ("approve", "revise", "reject"):
            stolen = self.client.post(
                f"/api/v1/research-runs/{run_id}/{action}",
                json={"comments": "take over"},
                headers={"Authorization": f"Bearer {other_token}"},
            )
            self.assertEqual(stolen.status_code, 404, action)
            self.assertEqual(stolen.json()["code"], "run_not_found")
            self.assertNotIn("Private transit notes", stolen.text)
            self.assertNotIn(token, stolen.text)
            anonymous = self.client.post(
                f"/api/v1/research-runs/{run_id}/{action}",
                json={"comments": "take over"},
            )
            self.assertEqual(anonymous.status_code, 401, action)
            self.assertEqual(anonymous.json()["code"], "unauthorized")

        owner_view = self.client.get(
            f"/api/v1/research-runs/{run_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(owner_view.status_code, 200)
        self.assertEqual(owner_view.json()["status"], "queued")
        self.assertEqual(owner_view.json()["topic"], "Private transit notes")

        other_usage = self.client.get("/api/v1/me/usage", headers={"Authorization": f"Bearer {other_token}"})
        self.assertEqual(other_usage.status_code, 200)
        self.assertNotIn(run_id, other_usage.json()["run_ids"])
        self.assertFalse(other_usage.json()["one_use_consumed"])
        self.assertNotIn("Private transit notes", other_usage.text)

    def test_idempotency_conflict_and_cancel_after_work_consume_quota(self) -> None:
        guest = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        token = guest.json()["guest_token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "http-key"}
        created = self.client.post("/api/v1/research-runs", json={"topic": "Widget latency"}, headers=headers)
        self.assertEqual(created.status_code, 202)
        run_id = created.json()["run_id"]

        conflict = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "A different topic"},
            headers=headers,
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "idempotency_conflict")
        self.assertNotIn(run_id, conflict.text)

        replay = self.client.post("/api/v1/research-runs", json={"topic": "Widget latency"}, headers=headers)
        self.assertEqual(replay.status_code, 202)
        self.assertTrue(replay.json()["reused"])
        self.assertEqual(replay.json()["run_id"], run_id)

        with self.factory() as session:
            stored = session.get(ResearchJob, run_id)
            stored.status = "running"
            stored.provider_work_started = 1
            stored.lease_owner = "worker-http"
            session.commit()

        cancelled = self.client.post(
            f"/api/v1/research-runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.json()["cancel_requested"])
        self.assertTrue(cancelled.json()["provider_work_started"])
        self.assertEqual(cancelled.json()["status"], "running")

        finalize_job(
            self.factory,
            run_id,
            ExecutionResult(status="completed", provider_work_started=True, approval_status="approved"),
            worker_id="worker-http",
        )
        finished = self.client.get(
            f"/api/v1/research-runs/{run_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.json()["status"], "cancelled")
        self.assertEqual(finished.json()["error_code"], "cancelled")
        self.assertTrue(finished.json()["provider_work_started"])

        again = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Widget latency"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "http-key-2"},
        )
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["code"], "quota_consumed")
        usage = self.client.get("/api/v1/me/usage", headers={"Authorization": f"Bearer {token}"})
        self.assertTrue(usage.json()["one_use_consumed"])
        self.assertFalse(usage.json()["one_use_refunded"])
        self.assertEqual(usage.json()["global_daily_starts"], 1)
        self.assertEqual(usage.json()["run_ids"], [run_id])

    def test_usage_aggregates_owner_ledger_totals(self) -> None:
        import uuid

        guest = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        token = guest.json()["guest_token"]
        created = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Ledger totals"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "ledger-key"},
        )
        self.assertEqual(created.status_code, 202)
        run_id = created.json()["run_id"]
        with self.factory() as session:
            identity = identity_from_token(session, token)
            session.add(
                UsageLedger(
                    id=str(uuid.uuid4()),
                    job_id=run_id,
                    identity_id=identity.id,
                    provider=None,
                    model=None,
                    llm_calls=4,
                    prompt_tokens=1200,
                    completion_tokens=350,
                    total_tokens=1550,
                    estimated_cost_usd=None,
                    search_calls=3,
                    created_at=utc_now(),
                )
            )
            session.commit()
        usage = self.client.get("/api/v1/me/usage", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(usage.status_code, 200)
        body = usage.json()
        self.assertEqual(body["llm_calls"], 4)
        self.assertEqual(body["prompt_tokens"], 1200)
        self.assertEqual(body["completion_tokens"], 350)
        self.assertEqual(body["total_tokens"], 1550)
        self.assertEqual(body["search_calls"], 3)
        from backend.app.cost_estimate import estimate_usage_cost_usd

        self.assertEqual(
            body["estimated_cost_usd"],
            estimate_usage_cost_usd(prompt_tokens=1200, completion_tokens=350, search_calls=3),
        )

    def test_missing_idempotency_key_and_bad_turnstile(self) -> None:
        guest = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        token = guest.json()["guest_token"]
        missing = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Widget latency"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["code"], "missing_idempotency_key")
        rejected = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "nope"})
        self.assertEqual(rejected.status_code, 403)

    def test_database_outage_fails_closed(self) -> None:
        class _Broken:
            def __call__(self):
                raise SQLAlchemyError("postgresql://user:secret@db.example/researchmind")

        self.app.state.session_factory = _Broken()
        response = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "database_unavailable")
        self.assertNotIn("secret", response.text)
        self.assertNotIn("postgresql", response.text)
        ready = self.client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 503)
        self.assertEqual(ready.json()["database"], "unavailable")
        self.assertNotIn("secret", ready.text)


class TurnstileHttpTests(unittest.TestCase):
    def test_siteverify_success_and_failure(self) -> None:
        import httpx

        def _ok(request: httpx.Request) -> httpx.Response:
            body = request.content.decode()
            self.assertIn("response=token-1", body)
            self.assertIn("secret=test-secret", body)
            return httpx.Response(200, json={"success": True})

        verifier = HttpTurnstileVerifier(
            "test-secret",
            "https://example.test/siteverify",
            client=httpx.Client(transport=httpx.MockTransport(_ok)),
            allow_unpinned_url=True,
        )
        self.assertTrue(verifier.verify("token-1", None))

        def _no(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": False})

        rejected = HttpTurnstileVerifier(
            "test-secret",
            "https://example.test/siteverify",
            client=httpx.Client(transport=httpx.MockTransport(_no)),
            allow_unpinned_url=True,
        )
        self.assertFalse(rejected.verify("token-1", None))

    def test_siteverify_url_stays_on_cloudflare(self) -> None:
        from backend.app.jobs.turnstile import OFFICIAL_TURNSTILE_VERIFY_URL, build_turnstile_verifier

        pinned = HttpTurnstileVerifier("test-secret", OFFICIAL_TURNSTILE_VERIFY_URL)
        self.assertEqual(pinned.verify_url, OFFICIAL_TURNSTILE_VERIFY_URL)
        with self.assertRaises(ValueError):
            HttpTurnstileVerifier("test-secret", "https://example.test/siteverify")
        with self.assertRaises(ValueError):
            build_turnstile_verifier(secret="test-secret", verify_url="http://challenges.cloudflare.com/turnstile/v0/siteverify")
        built = build_turnstile_verifier(
            secret="test-secret",
            verify_url="https://challenges.cloudflare.com:443/turnstile/v0/siteverify",
        )
        self.assertEqual(built.verify_url, OFFICIAL_TURNSTILE_VERIFY_URL)


if __name__ == "__main__":
    unittest.main()
