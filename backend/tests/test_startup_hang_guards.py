"""Guards so Render Free cold starts still serve /docs and /health/live."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = ""
os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
os.environ["TURNSTILE_SECRET_KEY"] = ""

import inspect
import unittest

from fastapi.testclient import TestClient

from backend.app.core.config import clear_settings_cache
from backend.app.main import create_app, lifespan


class StartupHangGuardTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_settings_cache()

    def test_lifespan_defers_database_before_yield(self) -> None:
        source = inspect.getsource(lifespan)
        self.assertNotIn("run_retention_pass", source)
        self.assertIn("create_task", source)
        self.assertIn("_init_database", source)
        self.assertLess(source.index("create_task"), source.index("\n    yield"))
        self.assertIn("asyncio.to_thread(apply_migrations", source)
        self.assertIn("asyncio.to_thread(_recover_leases", source)

    def test_root_and_docs_accept_get_and_head(self) -> None:
        clear_settings_cache()
        app = create_app()
        client = TestClient(app)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.head("/").status_code, 200)
        self.assertEqual(client.get("/docs").status_code, 200)
        self.assertEqual(client.get("/openapi.json").status_code, 200)
        self.assertEqual(client.get("/api/v1/health/live").status_code, 200)
        self.assertEqual(client.head("/api/v1/health/live").status_code, 200)

    def test_docs_available_while_database_still_starting(self) -> None:
        """Root fix: HTTP binds before Postgres/Neon finishes waking."""
        clear_settings_cache()
        app = create_app()
        client = TestClient(app)
        # Lifespan already yielded (no DATABASE_URL). Simulate Neon still waking.
        app.state.database_starting = True
        app.state.session_factory = None
        self.assertEqual(client.get("/docs").status_code, 200)
        self.assertEqual(client.get("/api/v1/health/live").status_code, 200)
        ready = client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 503)
        self.assertEqual(ready.json()["database"], "starting")


if __name__ == "__main__":
    unittest.main()
