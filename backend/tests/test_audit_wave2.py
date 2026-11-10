"""Audit wave 2: stranded jobs, conditional cancel/review, wake, SSE, turnstile, retention."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = ""
os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
os.environ["TURNSTILE_SECRET_KEY"] = ""
os.environ["USE_MOCK_PROVIDER"] = "true"

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from backend.app.core.config import clear_settings_cache
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.db.models import DemoEntitlement, JobEvent, ResearchJob
from backend.app.graph import GraphLimits, ResearchGraphRunner
from backend.app.jobs.consumer import QueueConsumer, process_one
from backend.app.jobs.executor import ExecutionResult
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.lease import lease_next, recover_expired_leases
from backend.app.jobs.persist import _bounded_key, finalize_job
from backend.app.jobs.quota import (
    cancel_run,
    issue_guest_identity,
    identity_from_token,
    request_review,
    start_run,
)
from backend.app.jobs.retention import purge_expired_data
from backend.app.jobs.timeutil import add_days, add_seconds, utc_now
from backend.app.jobs.turnstile import HttpTurnstileVerifier, StaticTurnstileVerifier
from backend.app.main import create_app
from backend.tests.graph_fakes import LAB_HITS, LAB_PAGES, FixtureRetrieval, success_roles
from backend.tests.test_graph_workflow import _runner

BUDGETS = {"max_model_calls": 12, "max_wall_clock_seconds": 180}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = make_engine(f"sqlite:///{Path(self._tmp.name) / 'w2.sqlite3'}")
        apply_migrations(self.engine)
        self.factory = make_session_factory(self.engine)
        self.verifier = StaticTurnstileVerifier({"ok"})

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def token(self) -> str:
        with self.factory() as session:
            return issue_guest_identity(
                session, verifier=self.verifier, turnstile_token="ok", remote_ip=None, ttl_hours=24
            )

    def job(self, token: str | None = None, *, max_attempts: int = 3) -> str:
        token = token or self.token()
        with self.factory() as session:
            owner = identity_from_token(session, token)
            job, _ = start_run(
                session,
                identity_id=owner.id,
                topic="topic",
                idempotency_key="k" + token[:8],
                max_active=5,
                daily_cap=10,
                max_attempts=max_attempts,
                budgets=BUDGETS,
            )
            return job.id

    def update(self, job_id: str, **values: object) -> None:
        with self.factory() as session:
            session.execute(
                ResearchJob.__table__.update().where(ResearchJob.id == job_id).values(**values)
            )
            session.commit()

    def get(self, job_id: str) -> ResearchJob:
        with self.factory() as session:
            return session.get(ResearchJob, job_id)

    def owner(self, job_id: str) -> str:
        return self.get(job_id).owner_id


class StrandedJobTests(_Base):
    def test_queued_job_out_of_attempts_is_failed_and_refunded(self) -> None:
        job_id = self.job()
        self.update(job_id, attempts=3)
        with self.factory() as session:
            recover_expired_leases(session)
            session.commit()
        stored = self.get(job_id)
        self.assertEqual((stored.status, stored.error_code), ("failed", "stranded"))
        with self.factory() as session:
            self.assertEqual(session.get(DemoEntitlement, stored.owner_id).status, "refunded")

    def test_queued_job_with_cancel_flag_is_cancelled(self) -> None:
        job_id = self.job()
        self.update(job_id, cancel_requested=1)
        with self.factory() as session:
            recover_expired_leases(session)
            session.commit()
        self.assertEqual(self.get(job_id).status, "cancelled")

    def test_normal_queued_job_is_left_alone(self) -> None:
        job_id = self.job()
        with self.factory() as session:
            self.assertEqual(recover_expired_leases(session), [])
            session.commit()
        self.assertEqual(self.get(job_id).status, "queued")

    def test_finalize_failure_on_last_attempt_is_recovered(self) -> None:
        job_id = self.job(max_attempts=1)

        class _Done:
            def execute(self, _factory: object, _job_id: str) -> ExecutionResult:
                return ExecutionResult(status="completed", provider_work_started=True)

        with patch("backend.app.jobs.consumer.finalize_job", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                process_one(
                    session_factory=self.factory,
                    executor=_Done(),
                    worker_id="w",
                    lease_seconds=1,
                    heartbeat_seconds=60,
                )
        self.assertEqual(self.get(job_id).status, "running")
        with self.factory() as session:
            recover_expired_leases(session, now=add_seconds(utc_now(), 5))
            session.commit()
        self.assertEqual(self.get(job_id).status, "failed")


class CancelReviewTests(_Base):
    def test_cancel_queued_and_running(self) -> None:
        queued = self.job()
        with self.factory() as session:
            cancelled = cancel_run(session, queued, self.owner(queued))
        self.assertEqual(cancelled.status, "cancelled")
        running = self.job()
        self.update(running, status="running", lease_owner="w")
        with self.factory() as session:
            flagged = cancel_run(session, running, self.owner(running))
        self.assertEqual((flagged.status, flagged.cancel_requested), ("running", 1))

    def test_review_refused_after_cancel_flag(self) -> None:
        job_id = self.job()
        self.update(job_id, status="review_required", cancel_requested=1)
        with self.factory() as session, self.assertRaises(JobServiceError) as caught:
            request_review(session, job_id, self.owner(job_id), "approve", "")
        self.assertEqual(caught.exception.status_code, 409)

    def test_review_resume_can_lease_again_after_attempts_were_used(self) -> None:
        job_id = self.job()
        self.update(job_id, status="review_required", attempts=3)
        with self.factory() as session:
            request_review(session, job_id, self.owner(job_id), "approve", "ok")
        with self.factory() as session:
            leased = lease_next(session, worker_id="w", now=utc_now(), lease_seconds=60)
            session.commit()
        self.assertEqual(leased, job_id)

    def test_second_review_request_is_a_conflict(self) -> None:
        job_id = self.job()
        self.update(job_id, status="review_required")
        owner = self.owner(job_id)
        with self.factory() as session:
            request_review(session, job_id, owner, "approve", "")
        with self.factory() as session, self.assertRaises(JobServiceError) as caught:
            request_review(session, job_id, owner, "approve", "")
        self.assertEqual(caught.exception.code, "not_awaiting_review")


class PersistTests(_Base):
    def test_second_review_required_event_is_recorded(self) -> None:
        job_id = self.job()
        owner = self.owner(job_id)
        for attempt in range(2):
            if attempt:
                with self.factory() as session:
                    request_review(session, job_id, owner, "revise", "more")
            self.update(job_id, status="running", lease_owner="w")
            finalize_job(
                self.factory,
                job_id,
                ExecutionResult(status="review_required", provider_work_started=True),
                worker_id="w",
            )
        self.assertEqual(self.event_types(job_id).count("run.review_required"), 2)

    def test_finalize_does_not_repeat_the_graph_status_event(self) -> None:
        job_id = self.job()
        self.update(job_id, status="running", lease_owner="w")
        finalize_job(
            self.factory,
            job_id,
            ExecutionResult(
                status="failed",
                provider_work_started=True,
                events=[{"type": "run.failed", "event_id": 1, "payload": {}}],
            ),
            worker_id="w",
        )
        self.assertEqual(self.event_types(job_id).count("run.failed"), 1)

    def event_types(self, job_id: str) -> list[str]:
        with self.factory() as session:
            return [
                row.event_type
                for row in session.scalars(
                    select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.sequence_id)
                )
            ]

    def test_long_keys_do_not_collide_on_a_prefix(self) -> None:
        a, b = "x" * 90 + "a", "x" * 90 + "b"
        self.assertNotEqual(_bounded_key(a), _bounded_key(b))
        self.assertEqual(len(_bounded_key(a)), 80)
        self.assertEqual(_bounded_key("short"), "short")


class RetentionTests(_Base):
    def test_abandoned_review_required_is_purged_but_queued_is_kept(self) -> None:
        old = add_days(utc_now(), -5)
        stale, queued = self.job(), self.job()
        self.update(stale, status="review_required", updated_at=old)
        self.update(queued, created_at=old, updated_at=old)
        with self.factory() as session:
            purge_expired_data(session, retention_days=2)
            session.commit()
            self.assertIsNone(session.get(ResearchJob, stale))
            self.assertIsNotNone(session.get(ResearchJob, queued))


class MigrationTests(_Base):
    def test_index_cleanup(self) -> None:
        with self.engine.connect() as conn:
            names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
        self.assertIn("ix_usage_ledger_identity", names)
        self.assertNotIn("ix_job_events_run_seq", names)
        self.assertNotIn("ix_sources_job_url", names)
        self.assertIn("uq_job_events_sequence", names)


class TurnstileTests(unittest.TestCase):
    def _verifier(self, body: dict, seen: list, allowed: frozenset[str]) -> HttpTurnstileVerifier:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.content.decode())
            return httpx.Response(200, json=body)

        return HttpTurnstileVerifier(
            "secret",
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            allowed_hostnames=allowed,
        )

    def test_hostname_must_match_when_present(self) -> None:
        allowed = frozenset({"console.example.com"})
        seen: list[str] = []
        self.assertTrue(self._verifier({"success": True, "hostname": "Console.example.com"}, seen, allowed).verify("t", None))
        self.assertFalse(self._verifier({"success": True, "hostname": "evil.test"}, seen, allowed).verify("t", None))
        self.assertTrue(self._verifier({"success": True}, seen, allowed).verify("t", None))
        self.assertTrue(self._verifier({"success": True, "hostname": "evil.test"}, seen, frozenset()).verify("t", None))

    def test_remoteip_is_not_sent_by_the_guest_route(self) -> None:
        seen: list[str] = []
        verifier = self._verifier({"success": True}, seen, frozenset())
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(f"sqlite:///{Path(tmp) / 'g.sqlite3'}")
            apply_migrations(engine)
            app = create_app()
            app.state.session_factory = make_session_factory(engine)
            app.state.turnstile_verifier = verifier
            app.state.consumer_enabled = False
            response = TestClient(app).post(
                "/api/v1/guest-identities",
                json={"turnstile_token": "t"},
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            engine.dispose()
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("remoteip", seen[0])


class ApiTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.app = create_app()
        self.app.state.session_factory = self.factory
        self.app.state.turnstile_verifier = self.verifier
        self.app.state.consumer_enabled = False
        self.client = TestClient(self.app)
        self.bearer = self.token()
        self.headers = {"Authorization": f"Bearer {self.bearer}"}

    def test_identity_db_error_is_503_not_500(self) -> None:
        err = OperationalError("SELECT 1", {}, Exception("down"))
        for path in ("/api/v1/me/usage", "/api/v1/research-runs/abc", "/api/v1/research-runs/abc/events"):
            module = "usage" if "usage" in path else "runs"
            with patch(f"backend.app.api.v1.{module}.identity_from_token", side_effect=err):
                self.assertEqual(self.client.get(path, headers=self.headers).status_code, 503, path)

    def test_create_run_wakes_the_consumer(self) -> None:
        woke = threading.Event()

        class _Consumer:
            def wake(self) -> None:
                woke.set()

        self.app.state.consumer = _Consumer()
        response = self.client.post(
            "/api/v1/research-runs", json={"topic": "t"}, headers={**self.headers, "Idempotency-Key": "abc123"}
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(woke.is_set())

    def _queued_run(self) -> str:
        return self.client.post(
            "/api/v1/research-runs", json={"topic": "t"}, headers={**self.headers, "Idempotency-Key": "abc123"}
        ).json()["run_id"]

    def test_stream_builds_snapshot_once_while_nothing_changes(self) -> None:
        run_id = self._queued_run()
        self.app.state.sse_max_polls = 3
        with patch("backend.app.api.v1.stream.build_snapshot", return_value={"run_id": run_id}) as built:
            with patch("backend.app.api.v1.stream._POLL_SECONDS", 0.01):
                with self.client.stream("GET", f"/api/v1/research-runs/{run_id}/events/stream", headers=self.headers) as r:
                    "".join(r.iter_text())
        self.assertEqual(built.call_count, 1)

    def test_stream_lifetime_cap_sends_transient_close(self) -> None:
        run_id = self._queued_run()
        self.app.state.sse_max_seconds = 0
        with self.client.stream("GET", f"/api/v1/research-runs/{run_id}/events/stream", headers=self.headers) as r:
            body = "".join(r.iter_text())
        closed = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:") and "reconnect" in line]
        self.assertEqual(closed, [{"status": "reconnect"}])


class ConsumerTests(_Base):
    def test_wake_cuts_the_idle_wait_short(self) -> None:
        job_id = self.job()
        self.update(job_id, next_attempt_at=add_days(utc_now(), 1))  # not leasable yet
        ran = threading.Event()

        class _Executor:
            def execute(self, _factory: object, _job_id: str) -> ExecutionResult:
                ran.set()
                return ExecutionResult(status="completed", provider_work_started=True)

        consumer = QueueConsumer(
            session_factory=self.factory,
            executor=_Executor(),
            worker_id="w",
            poll_seconds=0.01,
            idle_poll_seconds=60,
            retention_enabled=False,
        )
        consumer.start()
        try:
            time.sleep(0.2)  # first pass found nothing and is now idling
            self.update(job_id, next_attempt_at=None)
            self.assertFalse(ran.wait(0.3))  # still idling without a wake
            consumer.wake()
            self.assertTrue(ran.wait(3))
        finally:
            consumer.stop()


class CodexReviewTests(_Base):
    def test_lost_lease_is_visible_to_the_executor(self) -> None:
        from backend.app.jobs.executor import LEASE_LOST

        job_id = self.job()
        seen: list[bool] = []

        class _Executor:
            def execute(self, _factory: object, _job_id: str) -> ExecutionResult:
                lost = LEASE_LOST.get()
                assert lost is not None, "consumer must hand the lost-lease event to the executor"
                seen.append(lost.wait(2))  # heartbeat reports the lease gone
                return ExecutionResult(status="completed", provider_work_started=True)

        with patch("backend.app.jobs.consumer.heartbeat", return_value=False):
            process_one(
                session_factory=self.factory,
                executor=_Executor(),
                worker_id="w",
                lease_seconds=60,
                heartbeat_seconds=0.05,
            )
        self.assertEqual(seen, [True])

    def test_failed_poll_retries_before_the_idle_interval(self) -> None:
        calls: list[float] = []

        def _flaky(**_kwargs: object) -> None:
            calls.append(time.monotonic())
            if len(calls) == 1:
                raise OperationalError("SELECT 1", {}, Exception("down"))
            return None

        consumer = QueueConsumer(
            session_factory=self.factory,
            executor=object(),
            worker_id="w",
            poll_seconds=0.01,
            idle_poll_seconds=60,
            retention_enabled=False,
        )
        with patch("backend.app.jobs.consumer.process_one", side_effect=_flaky), patch(
            "backend.app.jobs.consumer.FAILED_POLL_RETRY_SECONDS", 0.05
        ):
            consumer.start()
            try:
                deadline = time.monotonic() + 3
                while len(calls) < 2 and time.monotonic() < deadline:
                    time.sleep(0.02)
            finally:
                consumer.stop()
        self.assertGreaterEqual(len(calls), 2, "a failed poll must not wait the 60 s idle interval")

    def test_get_run_includes_ledger_usage(self) -> None:
        owner_token = self.token()
        job_id = self.job(owner_token)
        self.update(job_id, status="running", lease_owner="w")
        finalize_job(
            self.factory,
            job_id,
            ExecutionResult(
                status="review_required",
                provider_work_started=True,
                usage={"llm_calls": 4, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            ),
            worker_id="w",
        )
        app = create_app()
        app.state.session_factory = self.factory
        app.state.consumer_enabled = False
        body = TestClient(app).get(
            f"/api/v1/research-runs/{job_id}", headers={"Authorization": f"Bearer {owner_token}"}
        ).json()
        self.assertEqual(body["status"], "review_required")
        self.assertEqual(body["usage"]["llm_calls"], 4)


class LostLeaseTests(unittest.TestCase):
    def test_runner_stops_between_steps_when_told_to(self) -> None:
        runner, _router = _runner(success_roles(1), FixtureRetrieval(LAB_HITS, LAB_PAGES))
        runner.should_stop = lambda: True
        outcome = runner.start("Widget latency", run_id="lost")
        self.assertTrue(outcome.expired)


if __name__ == "__main__":
    unittest.main()
