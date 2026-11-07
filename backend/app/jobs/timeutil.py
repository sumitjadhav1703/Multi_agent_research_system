"""UTC timestamps stored as ISO-8601 strings so SQLite and Postgres compare the same way."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_day(now: str | None = None) -> str:
    return (now or utc_now())[:10]


def add_seconds(now: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(now)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed + timedelta(seconds=seconds)).isoformat()


def add_days(now: str, days: int) -> str:
    """Shift an ISO-8601 UTC timestamp by whole days (negative allowed)."""
    return add_seconds(now, int(days) * 24 * 60 * 60)
