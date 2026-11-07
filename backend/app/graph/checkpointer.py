"""Checkpoint selection.

Memory saver is the default for tests and for SQLite, which cannot store the
LangGraph Postgres schema. PostgreSQL uses langgraph-checkpoint-postgres.
AsyncPostgresSaver.setup() creates that schema. The Milestone 2 runner is
synchronous, so the worker keeps a PostgresSaver on the same tables.

An interrupted model call can run again. This is not exactly-once execution.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any


def build_checkpointer(kind: str = "memory", *, database_url: str | None = None) -> Any:
    del database_url
    if kind == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    if kind == "postgres":
        raise RuntimeError(
            "Postgres checkpoints need an open psycopg connection. "
            "Call open_postgres_checkpointer(database_url) and AsyncPostgresSaver.setup(). "
            "A postgresql DATABASE_URL is required; in-memory state is not a substitute."
        )
    raise ValueError(f"Unknown checkpointer kind '{kind}'.")


def _require_postgres_url(database_url: str) -> str:
    if not database_url or not database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must be a postgresql URL for the Postgres checkpointer.")
    return database_url


@contextmanager
def open_postgres_checkpointer(database_url: str) -> Iterator[Any]:
    """Yield a sync PostgresSaver. The caller keeps this context open."""
    url = _require_postgres_url(database_url)
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(url) as saver:
        yield saver


@asynccontextmanager
async def open_async_postgres_checkpointer(database_url: str) -> Any:
    url = _require_postgres_url(database_url)
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        yield saver


async def setup_postgres_checkpointer(database_url: str) -> None:
    """Run LangGraph's checkpoint migrations. Safe to call more than once."""
    async with open_async_postgres_checkpointer(database_url) as saver:
        await saver.setup()
