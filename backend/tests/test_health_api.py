"""FastAPI health endpoint smoke tests."""
from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient


class HealthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["USE_MOCK_PROVIDER"] = "true"
        os.environ["DATABASE_URL"] = ""
        os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
        os.environ["TURNSTILE_SECRET_KEY"] = ""
        from backend.app.core.config import DEFAULT_FREE_ALLOWLIST, clear_settings_cache

        os.environ["FREE_MODEL_ALLOWLIST"] = ",".join(DEFAULT_FREE_ALLOWLIST)

        clear_settings_cache()
        from backend.app.main import app

        cls.client = TestClient(app)

    def test_live(self) -> None:
        response = self.client.get("/api/v1/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_ready(self) -> None:
        response = self.client.get("/api/v1/health/ready")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["database"], "not_configured")
        for leaked in ("app_env", "allow_paid_models", "roles", "allowlist_size"):
            self.assertNotIn(leaked, body)

    def test_root(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service"], "researchmind")


if __name__ == "__main__":
    unittest.main()
