"""Retention scheduling on the queue consumer (failure backoff)."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = ""
os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
os.environ["TURNSTILE_SECRET_KEY"] = ""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.core.config import clear_settings_cache
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.jobs.consumer import QueueConsumer
from backend.app.jobs.timeutil import add_seconds, utc_now


class RetentionConsumerScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "sched.sqlite3"
        self.engine = make_engine(f"sqlite:///{path}")
        apply_migrations(self.engine)
        self.factory = make_session_factory(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def test_failed_retention_still_advances_schedule(self) -> None:
        consumer = QueueConsumer(
            session_factory=self.factory,
            executor=MagicMock(),
            worker_id="test-worker",
            retention_enabled=True,
            retention_days=2,
            retention_interval_seconds=3600,
            retention_batch_size=100,
        )
        with patch(
            "backend.app.jobs.consumer.run_retention_pass",
            side_effect=RuntimeError("db down"),
        ) as mocked:
            consumer.maybe_purge_retention(force=True)
            self.assertEqual(mocked.call_count, 1)
            stamped = consumer._last_retention_at
            self.assertIsNotNone(stamped)

            # Must not retry on the next idle poll while the interval remains.
            consumer.maybe_purge_retention(force=False)
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(consumer._last_retention_at, stamped)

            # After the configured interval, another attempt is allowed.
            consumer._last_retention_at = add_seconds(utc_now(), -3600)
            consumer.maybe_purge_retention(force=False)
            self.assertEqual(mocked.call_count, 2)
            self.assertIsNotNone(consumer._last_retention_at)


if __name__ == "__main__":
    unittest.main()
