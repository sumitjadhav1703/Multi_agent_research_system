"""Exact CORS allowlist. Wildcard origins must not boot."""
from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core.config import Settings, clear_settings_cache


class CorsConfigTests(unittest.TestCase):
    def test_empty_allowlist_is_same_origin_only(self) -> None:
        settings = Settings(_env_file=None, USE_MOCK_PROVIDER="true", CORS_ORIGINS="")
        self.assertEqual(settings.cors_origin_list, [])

    def test_exact_origins_are_normalized(self) -> None:
        settings = Settings(
            _env_file=None,
            USE_MOCK_PROVIDER="true",
            CORS_ORIGINS="https://console.example/, http://127.0.0.1:5173, https://console.example:443",
        )
        self.assertEqual(
            settings.cors_origin_list,
            ["https://console.example", "http://127.0.0.1:5173"],
        )

    def test_wildcard_is_rejected(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            Settings(_env_file=None, USE_MOCK_PROVIDER="true", CORS_ORIGINS="*")
        self.assertIn("wildcard", str(caught.exception).lower())

    def test_path_and_credentials_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, USE_MOCK_PROVIDER="true", CORS_ORIGINS="https://console.example/app")
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                USE_MOCK_PROVIDER="true",
                CORS_ORIGINS="https://user:secret@console.example",
            )


class CorsMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous = os.environ.get("CORS_ORIGINS")
        os.environ["USE_MOCK_PROVIDER"] = "true"
        os.environ["DATABASE_URL"] = ""
        os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
        os.environ["TURNSTILE_SECRET_KEY"] = ""
        clear_settings_cache()

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("CORS_ORIGINS", None)
        else:
            os.environ["CORS_ORIGINS"] = self._previous
        clear_settings_cache()

    def test_allowed_origin_preflight_and_get(self) -> None:
        os.environ["CORS_ORIGINS"] = "https://console.example"
        clear_settings_cache()
        from backend.app.main import create_app

        client = TestClient(create_app())
        preflight = client.options(
            "/api/v1/health/live",
            headers={
                "Origin": "https://console.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,idempotency-key,last-event-id",
            },
        )
        self.assertIn(preflight.status_code, (200, 204))
        self.assertEqual(preflight.headers.get("access-control-allow-origin"), "https://console.example")
        self.assertNotEqual(preflight.headers.get("access-control-allow-origin"), "*")
        self.assertNotEqual(preflight.headers.get("access-control-allow-credentials"), "true")
        allow_headers = (preflight.headers.get("access-control-allow-headers") or "").lower()
        self.assertIn("authorization", allow_headers)
        self.assertIn("idempotency-key", allow_headers)
        self.assertIn("last-event-id", allow_headers)

        live = client.get("/api/v1/health/live", headers={"Origin": "https://console.example"})
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.headers.get("access-control-allow-origin"), "https://console.example")

    def test_other_origin_is_not_echoed(self) -> None:
        os.environ["CORS_ORIGINS"] = "https://console.example"
        clear_settings_cache()
        from backend.app.main import create_app

        client = TestClient(create_app())
        response = client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_unset_allowlist_sends_no_cors_header(self) -> None:
        os.environ["CORS_ORIGINS"] = ""
        clear_settings_cache()
        from backend.app.main import create_app

        client = TestClient(create_app())
        response = client.get("/api/v1/health/live", headers={"Origin": "https://console.example"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
