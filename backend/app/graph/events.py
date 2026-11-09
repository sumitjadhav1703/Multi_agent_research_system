"""Graph events shaped for a later SSE replay log.

Payloads stay small and must not carry prompts, page dumps or credentials.
`event_id` is assigned when a run outcome is materialized. Parallel workers
only append events; they do not pick the monotonic id.
"""
from __future__ import annotations

from typing import Any


def emit(event_type: str, node: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "type": event_type,
        "node": node,
        "payload": _sanitize(payload or {}),
    }
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(event)
    except Exception:
        # invoke() without a stream writer is a normal unit-test path.
        pass
    return event


def number_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign stable event_id values. Never renumber existing ids from 1.

    Resume paths append new events onto a checkpoint that already carried
    numbered events. Renumbering from 1 collides with ids already persisted
    (for example review.awaiting vs review.resumed) and the job log drops
    the later event.
    """
    next_id = 1
    for event in events:
        existing = event.get("event_id")
        if isinstance(existing, int) and existing >= next_id:
            next_id = existing + 1
    numbered: list[dict[str, Any]] = []
    for event in events:
        item = dict(event)
        existing = item.get("event_id")
        if isinstance(existing, int) and existing > 0:
            numbered.append(item)
            continue
        item["event_id"] = next_id
        next_id += 1
        numbered.append(item)
    return numbered


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "authorization", "messages", "prompt", "raw"}
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in blocked:
            continue
        clean[key] = _shrink(value)
    return clean


def _shrink(value: Any) -> Any:
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, list):
        return [_shrink(item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(key): _shrink(item) for key, item in list(value.items())[:20]}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]
