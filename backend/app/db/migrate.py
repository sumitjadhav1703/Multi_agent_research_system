"""Apply versioned SQL files in filename order. Re-running a file is a no-op."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.jobs.timeutil import utc_now

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def apply_migrations(engine: Engine, *, directory: Path | None = None) -> list[str]:
    root = directory or MIGRATIONS_DIR
    applied_now: list[str] = []
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(128) PRIMARY KEY,
                    applied_at VARCHAR(40) NOT NULL
                )
                """
            )
        )
        existing = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        for path in sorted(root.glob("*.sql")):
            if path.name in existing:
                continue
            for statement in _split_sql(path.read_text(encoding="utf-8")):
                conn.execute(text(statement))
            conn.execute(
                text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :applied_at)"),
                {"version": path.name, "applied_at": utc_now()},
            )
            applied_now.append(path.name)
    return applied_now


def _split_sql(script: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement.endswith(";"):
                statement = statement[:-1].strip()
            buffer = []
            if statement:
                statements.append(statement)
    leftover = "\n".join(buffer).strip()
    if leftover:
        raise ValueError("SQL migration has a statement without a trailing semicolon.")
    return statements
