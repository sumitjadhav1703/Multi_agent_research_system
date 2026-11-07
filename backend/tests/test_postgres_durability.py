"""Postgres lease and LangGraph checkpoint checks.

Skipped when local Postgres client tools cannot start a throwaway cluster.
SQLite tests do not claim FOR UPDATE SKIP LOCKED.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.db.models import GuestIdentity, ResearchJob
from backend.app.graph.checkpointer import open_postgres_checkpointer, setup_postgres_checkpointer
from backend.app.graph.runner import ResearchGraphRunner
from backend.app.jobs.lease import lease_next
from backend.app.jobs.timeutil import utc_now
from backend.app.schemas.research import ReviewDecision
from backend.tests.graph_fakes import (
    LAB_HITS,
    LAB_PAGES,
    FixtureRetrieval,
    client_for,
    scripted_behavior,
    success_roles,
)
from backend.tests.helpers import mock_settings

_TOOLS = ("initdb", "pg_ctl", "createdb")


def _postgres_available() -> bool:
    return all(shutil.which(tool) for tool in _TOOLS)


@unittest.skipUnless(_postgres_available(), "initdb/pg_ctl/createdb are not installed")
class PostgresDurabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._root = Path(tempfile.mkdtemp(prefix="rm-m3-pg-"))
        datadir = cls._root / "data"
        port = 56000 + (os.getpid() % 1000)
        cls.url = f"postgresql://researchmind@127.0.0.1:{port}/researchmind_test"
        cls._datadir = datadir
        try:
            subprocess.run(
                ["initdb", "-D", str(datadir), "-U", "researchmind", "-A", "trust"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "pg_ctl",
                    "-D",
                    str(datadir),
                    "-l",
                    str(cls._root / "server.log"),
                    "-o",
                    f"-p {port} -k {cls._root} -c listen_addresses=127.0.0.1",
                    "start",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["createdb", "-h", "127.0.0.1", "-p", str(port), "-U", "researchmind", "researchmind_test"],
                check=True,
                capture_output=True,
            )
        except Exception as exc:
            cls._stop()
            raise unittest.SkipTest(f"throwaway postgres did not start ({type(exc).__name__})") from None

    @classmethod
    def tearDownClass(cls) -> None:
        cls._stop()

    @classmethod
    def _stop(cls) -> None:
        datadir = getattr(cls, "_datadir", None)
        if datadir and datadir.exists():
            subprocess.run(["pg_ctl", "-D", str(datadir), "-m", "fast", "stop"], capture_output=True)
        root = getattr(cls, "_root", None)
        if root and root.exists():
            shutil.rmtree(root, ignore_errors=True)

    def test_skip_locked_leases_two_jobs(self) -> None:
        engine = make_engine(self.url)
        apply_migrations(engine)
        factory = make_session_factory(engine)
        now = utc_now()
        with factory() as session:
            session.add(GuestIdentity(id="pg-owner", created_at=now, expires_at=None, turnstile_verified=1))
            session.flush()
            for job_id in ("pg-job-1", "pg-job-2"):
                session.add(
                    ResearchJob(
                        id=job_id,
                        owner_id="pg-owner",
                        topic="Widget latency",
                        status="queued",
                        idempotency_key=job_id,
                        thread_id=job_id,
                        attempts=0,
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

        first = factory()
        second = factory()
        try:
            first.execute(text("SET LOCAL lock_timeout = '2s'"))
            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            leased_first = lease_next(first, worker_id="a", now=now, lease_seconds=30)
            leased_second = lease_next(second, worker_id="b", now=now, lease_seconds=30)
            self.assertIsNotNone(leased_first)
            self.assertIsNotNone(leased_second)
            self.assertNotEqual(leased_first, leased_second)
            first.commit()
            second.commit()
        finally:
            first.close()
            second.close()
            engine.dispose()

    def test_checkpoint_survives_a_new_connection(self) -> None:
        asyncio.run(setup_postgres_checkpointer(self.url))
        client, _router = client_for(scripted_behavior(success_roles(1)))
        retrieval = FixtureRetrieval(LAB_HITS, LAB_PAGES)
        with open_postgres_checkpointer(self.url) as saver:
            runner = ResearchGraphRunner(
                model_client=client,
                retrieval=retrieval,
                checkpointer=saver,
            )
            paused = runner.start("Widget latency", run_id="pg-thread", owner_id="pg-owner")
            self.assertTrue(paused.interrupted)
        with open_postgres_checkpointer(self.url) as saver:
            runner = ResearchGraphRunner(
                model_client=client,
                retrieval=retrieval,
                checkpointer=saver,
            )
            has_values, interrupted, _state = runner.peek("pg-thread")
            self.assertTrue(has_values)
            self.assertTrue(interrupted)
            approved = runner.resume("pg-thread", ReviewDecision(action="approve"))
            self.assertEqual(approved.approval_status, "approved")
            self.assertFalse(approved.interrupted)
