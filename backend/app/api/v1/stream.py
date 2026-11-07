"""SSE replay for one owned research run.

`GET /research-runs/{id}/events` stays JSON. This route is the stream:

`GET /research-runs/{id}/events/stream`

The bearer token is read from the Authorization header. Query parameters are
ignored, so a token in the URL does not authenticate. `Last-Event-ID` is the
last `sequence_id` the client has applied. Rows with a higher sequence are
replayed from the database.

`snapshot` is assembled on connect from persisted report, source, passage,
claim, and usage rows. It is not stored as a job event and has no SSE id, so
it does not move the replay cursor. Unknown usage stays null.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.v1.deps import bearer_token
from backend.app.api.v1.snapshot import build_snapshot
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.quota import TERMINAL_STATUSES, get_owned_job, identity_from_token, list_events

router = APIRouter(tags=["research-runs"])

_POLL_SECONDS = 0.5
_DEFAULT_HEARTBEAT_SECONDS = 15.0


def _parse_last_event_id(value: str | None) -> int:
    if not value:
        return 0
    try:
        parsed = int(value.strip())
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _format_sse(event: str, data: dict[str, object], event_id: int | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def _poll(
    factory: sessionmaker[Session],
    run_id: str,
    owner_id: str,
    after: int,
) -> tuple[str, list[dict[str, object]], dict[str, object]]:
    session = factory()
    try:
        job = get_owned_job(session, run_id, owner_id)
        rows = list_events(session, run_id, owner_id, after=after)
        events = [
            {
                "sequence_id": row.sequence_id,
                "type": row.event_type,
                "payload": _payload(row.payload),
                "created_at": row.created_at,
            }
            for row in rows
        ]
        return job.status, events, build_snapshot(session, run_id)
    finally:
        session.close()


def _payload(raw: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _heartbeat_seconds(request: Request) -> float:
    raw = getattr(request.app.state, "sse_heartbeat_seconds", _DEFAULT_HEARTBEAT_SECONDS)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_HEARTBEAT_SECONDS
    return min(60.0, max(0.2, value))


@router.get("/research-runs/{run_id}/events/stream")
async def stream_run_events(
    run_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    token = bearer_token(authorization)
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise JobServiceError(503, "database_unavailable", "Database is unavailable.")
    session = factory()
    try:
        identity = identity_from_token(session, token)
        get_owned_job(session, run_id, identity.id)
        owner_id = identity.id
    finally:
        session.close()

    after = _parse_last_event_id(last_event_id)
    heartbeat_every = _heartbeat_seconds(request)
    max_polls = getattr(request.app.state, "sse_max_polls", None)

    async def generate() -> AsyncIterator[str]:
        cursor = after
        last_signature: str | None = None
        last_beat = time.monotonic()
        polls = 0
        yield ": heartbeat\n\n"
        while True:
            if await request.is_disconnected():
                return
            polls += 1
            try:
                status, events, snapshot = _poll(factory, run_id, owner_id, cursor)
            except JobServiceError:
                yield _format_sse("stream.closed", {"status": "unavailable"})
                return
            except Exception:
                yield _format_sse("stream.closed", {"status": "unavailable"})
                return
            for event in events:
                sequence = event.get("sequence_id")
                event_id = sequence if isinstance(sequence, int) else None
                yield _format_sse(str(event.get("type") or "run.event"), event, event_id)
                if isinstance(sequence, int):
                    cursor = sequence
            signature = json.dumps(snapshot, sort_keys=True, default=str)
            if signature != last_signature:
                yield _format_sse("snapshot", snapshot)
                last_signature = signature
            if status in TERMINAL_STATUSES:
                yield _format_sse("stream.closed", {"status": status})
                return
            now = time.monotonic()
            if now - last_beat >= heartbeat_every:
                yield ": heartbeat\n\n"
                last_beat = now
            if isinstance(max_polls, int) and max_polls > 0 and polls >= max_polls:
                return
            await asyncio.sleep(_POLL_SECONDS)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
