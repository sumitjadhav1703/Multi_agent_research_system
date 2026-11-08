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
    JobEvent,
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

    def test_last_event_id_replays_only_later_monotonic_events(self) -> None:
        now = utc_now()
        with self.factory() as session:
            for sequence, event_type in (
                (2, "worker.started"),
                (3, "evidence.stored"),
                (4, "run.completed"),
            ):
                session.add(
                    JobEvent(
                        id=str(uuid.uuid4()),
                        job_id=self.run_id,
                        sequence_id=sequence,
                        event_type=event_type,
                        payload=json.dumps({"status": event_type, "sequence_id": sequence}),
                        created_at=now,
                    )
                )
            session.commit()

        full = [item for item in _parse_sse(self._stream({"Authorization": f"Bearer {self.token}"})) if item.get("id")]
        ids = [int(item["id"]) for item in full]
        self.assertEqual(ids, [1, 2, 3, 4])
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(
            [item["event"] for item in full],
            ["run.queued", "worker.started", "evidence.stored", "run.completed"],
        )

        mid_body = self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": "2"})
        mid = _parse_sse(mid_body)
        replayed = [item for item in mid if item.get("id")]
        self.assertEqual([item["id"] for item in replayed], ["3", "4"])
        self.assertEqual([item["event"] for item in replayed], ["evidence.stored", "run.completed"])
        for item in replayed:
            payload = json.loads(item["data"])
            self.assertEqual(item["id"], str(payload["sequence_id"]))
            self.assertGreater(int(payload["sequence_id"]), 2)
        kinds = [item.get("event") for item in mid]
        self.assertNotIn("run.queued", kinds)
        self.assertNotIn("worker.started", kinds)
        self.assertIn("snapshot", kinds)
        self.assertEqual(kinds[-1], "stream.closed")
        self.assertFalse(any(item.get("event") == "snapshot" and item.get("id") for item in mid))

        finished = _parse_sse(self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": "4"}))
        self.assertEqual([item for item in finished if item.get("id")], [])
        self.assertEqual([item.get("event") for item in finished if item.get("event")], ["snapshot", "stream.closed"])

        ahead = _parse_sse(self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": "99"}))
        self.assertEqual([item for item in ahead if item.get("id")], [])
        self.assertIn("event: run.queued", self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": "0"}))
        self.assertIn("event: run.queued", self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": "-3"}))
        padded = [item for item in _parse_sse(self._stream({"Authorization": f"Bearer {self.token}", "Last-Event-ID": " 2 "})) if item.get("id")]
        self.assertEqual([item["id"] for item in padded], ["3", "4"])

        url = f"/api/v1/research-runs/{self.run_id}/events/stream?last_event_id=4&Last-Event-ID=4"
        with self.client.stream("GET", url, headers={"Authorization": f"Bearer {self.token}"}) as response:
            self.assertEqual(response.status_code, 200)
            queried = "".join(response.iter_text())
        self.assertIn("event: run.queued", queried)
        self.assertIn("id: 1", queried)

        page = self.client.get(
            f"/api/v1/research-runs/{self.run_id}/events?after=2",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual([item["sequence_id"] for item in page.json()["events"]], [3, 4])

        hidden = self.client.get(
            f"/api/v1/research-runs/{self.run_id}/events/stream",
            headers={"Authorization": f"Bearer {self.other}", "Last-Event-ID": "1"},
        )
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(hidden.json()["code"], "run_not_found")
        self.assertNotIn("evidence.stored", hidden.text)
        self.assertNotIn("Stored title", hidden.text)

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
