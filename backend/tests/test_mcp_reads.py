"""MCP-facing JSON reads. They do not start a second run or reset quota."""
from __future__ import annotations

import json
import os

os.environ["DATABASE_URL"] = ""
os.environ["QUEUE_CONSUMER_ENABLED"] = "false"
os.environ["TURNSTILE_SECRET_KEY"] = ""
os.environ["USE_MOCK_PROVIDER"] = "true"

import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import clear_settings_cache
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.db.models import (
    EvidencePassage,
    ResearchClaim,
    ResearchJob,
    ResearchReport,
    ResearchSource,
)
from backend.app.jobs.timeutil import utc_now
from backend.app.jobs.turnstile import StaticTurnstileVerifier
from backend.app.main import create_app


class McpReadRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "mcp-reads.sqlite3"
        self.engine = make_engine(f"sqlite:///{path}")
        apply_migrations(self.engine)
        self.factory = make_session_factory(self.engine)
        self.app = create_app()
        self.app.state.session_factory = self.factory
        self.app.state.turnstile_verifier = StaticTurnstileVerifier({"ok"})
        self.app.state.consumer_enabled = False
        self.client = TestClient(self.app)
        guest = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        self.token = guest.json()["guest_token"]
        other = self.client.post("/api/v1/guest-identities", json={"turnstile_token": "ok"})
        self.other = other.json()["guest_token"]
        created = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "Public transit reliability"},
            headers={"Authorization": f"Bearer {self.token}", "Idempotency-Key": "mcp-read-key"},
        )
        self.assertEqual(created.status_code, 202)
        self.run_id = created.json()["run_id"]

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def _auth(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.token}"}

    def _seed(self) -> None:
        now = utc_now()
        with self.factory() as session:
            job = session.get(ResearchJob, self.run_id)
            assert job is not None
            session.add(
                ResearchReport(
                    id=str(uuid.uuid4()),
                    job_id=self.run_id,
                    version=1,
                    markdown="# Stored title\n\nBody cites ev_sq1_1.",
                    approval_state="approved",
                    created_at=now,
                )
            )
            session.add(
                ResearchSource(
                    id=str(uuid.uuid4()),
                    job_id=self.run_id,
                    source_key="src_sq1_1",
                    canonical_url="https://example.test/transit",
                    url="https://example.test/transit",
                    domain="example.test",
                    title="Transit note",
                    content_hash="abc",
                    extraction_method="snippet",
                    retrieved_at=now,
                    excerpt="A stored excerpt.",
                )
            )
            session.add(
                EvidencePassage(
                    id=str(uuid.uuid4()),
                    job_id=self.run_id,
                    evidence_key="ev_sq1_1",
                    source_key="src_sq1_1",
                    subquestion_id="sq1",
                    quote="A stored quote.",
                )
            )
            session.add(
                ResearchClaim(
                    id=str(uuid.uuid4()),
                    job_id=self.run_id,
                    claim_key="cl1",
                    claim_text="Reliability improved.",
                    status="insufficient",
                    verification_reason="Overlap was too small.",
                    evidence_ids_json=json.dumps(["ev_sq1_1", "ev_missing"]),
                )
            )
            session.commit()

    def test_report_sources_and_claim_are_owner_scoped(self) -> None:
        empty = self.client.get(f"/api/v1/research-runs/{self.run_id}/report", headers=self._auth())
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.json()["report"])
        self.assertEqual(empty.json()["citations"], [])
        self.assertNotIn(self.token, empty.text)

        self._seed()
        report = self.client.get(f"/api/v1/research-runs/{self.run_id}/report", headers=self._auth())
        self.assertEqual(report.status_code, 200)
        body = report.json()
        self.assertIn("ev_sq1_1", body["report"]["markdown"])
        self.assertEqual(body["citations"], [
            {
                "source_id": "src_sq1_1",
                "title": "Transit note",
                "url": "https://example.test/transit",
                "domain": "example.test",
            }
        ])
        self.assertNotIn("excerpt", json.dumps(body["citations"]))
        self.assertNotIn(self.token, report.text)

        sources = self.client.get(f"/api/v1/research-runs/{self.run_id}/sources", headers=self._auth())
        self.assertEqual(sources.status_code, 200)
        self.assertEqual(sources.json()["sources"][0]["source_id"], "src_sq1_1")
        self.assertEqual(sources.json()["sources"][0]["excerpt"], "A stored excerpt.")

        evidence = self.client.get(
            f"/api/v1/research-runs/{self.run_id}/claims/cl1/evidence",
            headers=self._auth(),
        )
        self.assertEqual(evidence.status_code, 200)
        found = evidence.json()
        self.assertEqual(found["claim"]["status"], "insufficient")
        self.assertEqual(found["passages"][0]["quote"], "A stored quote.")
        self.assertEqual(found["missing_evidence_ids"], ["ev_missing"])
        self.assertNotIn("identity_id", evidence.text)

        missing_claim = self.client.get(
            f"/api/v1/research-runs/{self.run_id}/claims/missing/evidence",
            headers=self._auth(),
        )
        self.assertEqual(missing_claim.status_code, 404)
        self.assertEqual(missing_claim.json()["code"], "claim_not_found")

        for path in (
            f"/api/v1/research-runs/{self.run_id}/report",
            f"/api/v1/research-runs/{self.run_id}/sources",
            f"/api/v1/research-runs/{self.run_id}/claims/cl1/evidence",
        ):
            hidden = self.client.get(path, headers=self._auth(self.other))
            self.assertEqual(hidden.status_code, 404, path)
            self.assertNotIn("Stored title", hidden.text)
            self.assertNotIn("stored quote", hidden.text.lower())
            missing = self.client.get(path)
            self.assertEqual(missing.status_code, 401, path)
            self.assertEqual(missing.json()["code"], "unauthorized")

        planted = "query-secret-token-value"
        leaked = self.client.get(
            f"/api/v1/research-runs/{self.run_id}/report?access_token={planted}&token={planted}"
        )
        self.assertEqual(leaked.status_code, 401)
        self.assertNotIn(planted, leaked.text)

    def test_reads_do_not_bypass_one_use_quota(self) -> None:
        self._seed()
        self.client.get(f"/api/v1/research-runs/{self.run_id}/report", headers=self._auth())
        self.client.get(f"/api/v1/research-runs/{self.run_id}/sources", headers=self._auth())
        again = self.client.post(
            "/api/v1/research-runs",
            json={"topic": "A second topic"},
            headers={**self._auth(), "Idempotency-Key": "mcp-read-second"},
        )
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["code"], "quota_consumed")

    def test_evaluation_summary_is_authenticated_and_shared(self) -> None:
        missing = self.client.get("/api/v1/evaluation/summary")
        self.assertEqual(missing.status_code, 401)

        first = self.client.get("/api/v1/evaluation/summary", headers=self._auth())
        second = self.client.get("/api/v1/evaluation/summary", headers=self._auth(self.other))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        body = first.json()
        self.assertTrue(body["published"])
        self.assertEqual(body["deterministic"]["system"], "fixture")
        self.assertEqual(body["systems_compared"], [])
        # Published offline harness may be measured (Meta Muse fixture probe) or not.
        self.assertIn("measured", body)
        self.assertIn("judge", body)
        self.assertEqual(body["judge"].get("measured"), body.get("measured"))
        encoded = json.dumps(body)
        self.assertNotIn(self.token, encoded)
        self.assertNotIn(self.token, first.text)
        # Do not invent a percent accuracy field for guests.
        self.assertNotIn("accuracy_percent", encoded)
