"""Boot stays up when the database, checkpointer, retention, or consumer fails.

Settings validation, including CORS_ORIGINS, still fails closed.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["USE_MOCK_PROVIDER"] = "true"
os.environ["DATABASE_URL"] = ""
os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
os.environ["TURNSTILE_SECRET_KEY"] = ""
os.environ["CORS_ORIGINS"] = ""

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core.config import clear_settings_cache
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.jobs.consumer import QueueConsumer
from backend.app.main import create_app
from backend.app.observability.logging import JsonFormatter

_SECRET_URL = "postgresql://user:supersecret@db.internal/researchmind"
_ENV_KEYS = (
    "USE_MOCK_PROVIDER",
    "DATABASE_URL",
    "QUEUE_CONSUMER_ENABLED",
    "TURNSTILE_SECRET_KEY",
    "CORS_ORIGINS",
    "DATA_RETENTION_ENABLED",
)


class _Idle:
    def execute(self, _factory: object, job_id: str) -> None:
        raise AssertionError(job_id)


class LifespanResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        os.environ["USE_MOCK_PROVIDER"] = "true"
        os.environ["DATABASE_URL"] = ""
        os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
        os.environ["TURNSTILE_SECRET_KEY"] = ""
        os.environ["CORS_ORIGINS"] = ""
        os.environ["DATA_RETENTION_ENABLED"] = "true"
        clear_settings_cache()

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_settings_cache()

    def test_database_unavailable_at_startup_still_serves_liveness(self) -> None:
        os.environ["DATABASE_URL"] = _SECRET_URL
        os.environ["QUEUE_CONSUMER_ENABLED"] = "true"
        clear_settings_cache()
        with self.assertLogs("researchmind.telemetry", level="ERROR") as captured:
            with (
                patch("backend.app.main.make_engine", side_effect=RuntimeError(_SECRET_URL)),
                patch("backend.app.api.v1.health.make_engine") as health_engine,
                patch("backend.app.api.v1.health.ping") as health_ping,
            ):
                with TestClient(create_app()) as client:
                    self._wait_for_database_init(client.app)
                    live = client.get("/api/v1/health/live")
                    ready = client.get("/api/v1/health/ready")
                    self.assertIsNone(getattr(client.app.state, "consumer", None))
                    self.assertIsNone(client.app.state.session_factory)
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["status"], "ok")
        self.assertEqual(ready.status_code, 503)
        self.assertEqual(ready.json()["status"], "not_ready")
        self.assertEqual(ready.json()["database"], "unavailable")
        self.assertNotIn("supersecret", ready.text)
        self.assertNotIn("postgresql://", ready.text)
        health_engine.assert_not_called()
        health_ping.assert_not_called()
        self._assert_class_only(captured.records, "database.startup_failed", "RuntimeError")

    def test_checkpointer_failure_does_not_kill_boot(self) -> None:
        os.environ["DATABASE_URL"] = _SECRET_URL
        os.environ["QUEUE_CONSUMER_ENABLED"] = "true"
        clear_settings_cache()
        engine = MagicMock()
        with self.assertLogs("researchmind.telemetry", level="ERROR") as captured:
            with (
                patch("backend.app.main.make_engine", return_value=engine),
                patch("backend.app.main.apply_migrations"),
                patch("backend.app.main.make_session_factory", return_value=MagicMock()),
                patch(
                    "backend.app.main.setup_postgres_checkpointer",
                    side_effect=ConnectionError(_SECRET_URL),
                ),
            ):
                with TestClient(create_app()) as client:
                    self._wait_for_database_init(client.app)
                    live = client.get("/api/v1/health/live")
                    ready = client.get("/api/v1/health/ready")
                    self.assertIsNone(getattr(client.app.state, "consumer", None))
        self.assertEqual(live.status_code, 200)
        self.assertEqual(ready.status_code, 503)
        self.assertEqual(ready.json()["database"], "unavailable")
        engine.dispose.assert_called_once()
        self._assert_class_only(captured.records, "database.startup_failed", "ConnectionError")

    def test_retention_failure_keeps_database_ready(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp.name) / 'boot.sqlite3'}"
        os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
        os.environ["DATA_RETENTION_ENABLED"] = "true"
        clear_settings_cache()
        with self.assertLogs("researchmind.telemetry", level="ERROR") as captured:
            with patch("backend.app.main.run_retention_pass", side_effect=RuntimeError(_SECRET_URL)):
                with TestClient(create_app()) as client:
                    self._wait_for_database_init(client.app)
                    live = client.get("/api/v1/health/live")
                    ready = client.get("/api/v1/health/ready")
                    self.assertIsNone(client.app.state.database_startup_error)
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["status"], "ok")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")
        self.assertEqual(ready.json()["database"], "ok")
        self.assertNotIn("supersecret", ready.text)
        self._assert_class_only(captured.records, "retention.startup_failed", "RuntimeError")

    def test_second_consumer_start_is_refused_and_app_still_serves(self) -> None:
        blocker_dir = tempfile.TemporaryDirectory()
        app_dir = tempfile.TemporaryDirectory()
        self.addCleanup(blocker_dir.cleanup)
        self.addCleanup(app_dir.cleanup)
        blocker_engine = make_engine(f"sqlite:///{Path(blocker_dir.name) / 'blocker.sqlite3'}")
        apply_migrations(blocker_engine)
        self.addCleanup(blocker_engine.dispose)
        blocker = QueueConsumer(
            session_factory=make_session_factory(blocker_engine),
            executor=_Idle(),
            worker_id="blocker",
            poll_seconds=0.2,
            retention_enabled=False,
        )
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(app_dir.name) / 'app.sqlite3'}"
        os.environ["QUEUE_CONSUMER_ENABLED"] = "true"
        os.environ["DATA_RETENTION_ENABLED"] = "false"
        clear_settings_cache()
        blocker.start()
        try:
            with self.assertLogs("researchmind.telemetry", level="ERROR") as captured:
                with TestClient(create_app()) as client:
                    self._wait_for_database_init(client.app)
                    live = client.get("/api/v1/health/live")
                    ready = client.get("/api/v1/health/ready")
                    self.assertIsNone(getattr(client.app.state, "consumer", None))
                    self.assertIsNotNone(blocker._thread)
                    assert blocker._thread is not None
                    self.assertTrue(blocker._thread.is_alive())
            self.assertEqual(live.status_code, 200)
            self.assertEqual(live.json()["status"], "ok")
            self.assertEqual(ready.status_code, 200)
            self.assertEqual(ready.json()["database"], "ok")
            self._assert_class_only(captured.records, "queue.consumer_start_failed", "RuntimeError")
            rendered = " ".join(JsonFormatter().format(record) for record in captured.records)
            self.assertNotIn("already running", rendered)
        finally:
            blocker.stop()

    def test_retention_failure_does_not_stop_the_consumer_loop(self) -> None:
        def factory() -> None:
            raise RuntimeError(_SECRET_URL)

        consumer = QueueConsumer(
            session_factory=factory,
            executor=_Idle(),
            worker_id="loop",
            poll_seconds=0.01,
            retention_enabled=True,
            retention_interval_seconds=3600,
        )
        processed = {"n": 0}

        def fake_process(**_kwargs: object) -> None:
            processed["n"] += 1
            consumer._stop.set()
            return None

        with self.assertLogs("researchmind.telemetry", level="ERROR") as captured:
            with patch("backend.app.jobs.consumer.process_one", side_effect=fake_process):
                consumer._loop()
        self.assertEqual(processed["n"], 1)
        self.assertIsNotNone(consumer._last_retention_at)
        self.assertTrue(any(record.getMessage() == "retention.failed" for record in captured.records))
        rendered = " ".join(JsonFormatter().format(record) for record in captured.records)
        self.assertNotIn("supersecret", rendered)
        self.assertNotIn("postgresql://", rendered)

    def test_bad_cors_fails_closed_at_settings_validation(self) -> None:
        os.environ["CORS_ORIGINS"] = "*"
        clear_settings_cache()
        with self.assertRaises(ValidationError) as caught:
            create_app()
        self.assertIn("wildcard", str(caught.exception).lower())

    def test_lifespan_does_not_swallow_invalid_cors(self) -> None:
        clear_settings_cache()
        application = create_app()
        os.environ["CORS_ORIGINS"] = "*"
        clear_settings_cache()
        with self.assertRaises(ValidationError) as caught:
            with TestClient(application):
                self.fail("lifespan served traffic with invalid CORS_ORIGINS")
        self.assertIn("wildcard", str(caught.exception).lower())

    def _wait_for_database_init(self, app: object, timeout: float = 2.0) -> None:
        """Background Neon init must finish before ready/unavailable assertions."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not getattr(app.state, "database_starting", False):
                return
            time.sleep(0.01)
        self.fail("database init task did not finish")

    def _assert_class_only(self, records: list[object], event: str, class_name: str) -> None:
        matches = [record for record in records if record.getMessage() == event]
        self.assertTrue(matches, event)
        for record in matches:
            self.assertIsNone(record.exc_info)
            fields = getattr(record, "telemetry", {})
            self.assertEqual(fields.get("error.class"), class_name)
            rendered = JsonFormatter().format(record)
            self.assertIn(class_name, rendered)
            self.assertNotIn("supersecret", rendered)
            self.assertNotIn("postgresql://", rendered)
            self.assertNotIn("DATABASE_URL", rendered)


if __name__ == "__main__":
    unittest.main()
