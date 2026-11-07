"""SSE replay. The JSON events route stays; this covers the stream only."""
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
    UsageLedger,
)
from backend.app.jobs.timeutil import utc_now
from backend.app.jobs.turnstile import StaticTurnstileVerifier
from backend.app.main import create_app


def _parse_sse(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    data: list[str] = []
    for line in body.splitlines():
        if line == "":
            if current or data:
                if data:
                    current["data"] = "\n".join(data)
                events.append(current)
            current = {}
            data = []
            continue
        if line.startswith(":"):
            current = {"comment": line[1:].strip()}
            events.append(current)
            current = {}
            continue
        if line.startswith("id:"):
            current["id"] = line[3:].strip()
        elif line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if current or data:
        if data:
            current["data"] = "\n".join(data)
        events.append(current)
    return events


class SseStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_settings_cache()
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "sse.sqlite3"
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
            headers={"Authorization": f"Bearer {self.token}", "Idempotency-Key": "sse-key"},
        )
        self.run_id = created.json()["run_id"]
        now = utc_now()
        with self.factory() as session:
            job = session.get(ResearchJob, self.run_id)
            assert job is not None
            job.status = "completed"
            job.approval_status = "approved"
            job.finished_at = now
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
                    evidence_ids_json=json.dumps(["ev_sq1_1"]),
                )
            )
            session.add(
                UsageLedger(
                    id=str(uuid.uuid4()),
                    job_id=self.run_id,
                    identity_id=job.owner_id,
                    llm_calls=2,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    estimated_cost_usd=None,
                    search_calls=None,
                    created_at=now,
                )
            )
            session.commit()

    def tearDown(self) -> None:
        self.engine.dispose()
        self._tmp.cleanup()
        clear_settings_cache()

    def _stream(self, headers: dict[str, str]) -> str:
        url = f"/api/v1/research-runs/{self.run_id}/events/stream"
        with self.client.stream("GET", url, headers=headers) as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            return "".join(response.iter_text())

    def test_replays_events_snapshot_and_last_event_id(self) -> None:
        body = self._stream({"Authorization": f"Bearer {self.token}"})
        events = _parse_sse(body)
        named = [item for item in events if item.get("event")]
        self.assertEqual(named[0]["event"], "run.queued")
        self.assertEqual(named[0]["id"], "1")
        queued = json.loads(named[0]["data"])
        self.assertEqual(queued["sequence_id"], 1)
        self.assertEqual(queued["type"], "run.queued")
        snapshot = json.loads(next(item["data"] for item in named if item["event"] == "snapshot"))
        self.assertIn("ev_sq1_1", snapshot["report"]["markdown"])
        self.assertEqual(snapshot["sources"][0]["extraction_method"], "snippet")
        self.assertEqual(snapshot["passages"][0]["quote"], "A stored quote.")
        self.assertEqual(snapshot["claims"][0]["status"], "insufficient")
        self.assertEqual(snapshot["usage"]["llm_calls"], 2)
        self.assertIsNone(snapshot["usage"]["prompt_tokens"])
        self.assertIsNone(snapshot["usage"]["search_calls"])
        self.assertIsNone(snapshot["usage"]["estimated_cost_usd"])
        self.assertNotIn("identity_id", json.dumps(snapshot))
        self.assertNotIn(self.token, body)
        closed = json.loads(next(item["data"] for item in named if item["event"] == "stream.closed"))
        self.assertEqual(closed["status"], "completed")

        replay = self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": "1"})
        replayed = [item for item in _parse_sse(replay) if item.get("event")]
        self.assertNotIn("run.queued", [item["event"] for item in replayed])
        self.assertIn("snapshot", [item["event"] for item in replayed])
        self.assertIn("stream.closed", [item["event"] for item in replayed])

        messy = self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": "nope"})
        self.assertIn("event: run.queued", messy)

    def test_ownership_auth_and_query_token_are_rejected(self) -> None:
        url = f"/api/v1/research-runs/{self.run_id}/events/stream"
        hidden = self.client.get(url, headers={"Authorization": f"Bearer {self.other}"})
        self.assertEqual(hidden.status_code, 404)
        self.assertIn("application/json", hidden.headers["content-type"])
        self.assertNotIn("Stored title", hidden.text)

        missing = self.client.get(url)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["code"], "unauthorized")

        planted = "query-secret-token-value"
        leaked = self.client.get(f"{url}?access_token={planted}&token={planted}")
        self.assertEqual(leaked.status_code, 401)
        self.assertNotIn(planted, leaked.text)

        still_json = self.client.get(
            f"/api/v1/research-runs/{self.run_id}/events",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(still_json.status_code, 200)
        self.assertIn("run.queued", [item["type"] for item in still_json.json()["events"]])
