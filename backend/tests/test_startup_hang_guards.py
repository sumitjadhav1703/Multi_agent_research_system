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

    def test_lifespan_does_not_run_retention_inline(self) -> None:
        source = inspect.getsource(lifespan)
        self.assertNotIn("run_retention_pass", source)
        self.assertIn("recover_expired_leases", source)

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


if __name__ == "__main__":
    unittest.main()
