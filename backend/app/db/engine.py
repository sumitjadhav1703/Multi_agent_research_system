"""Engine and session factory. SQLite is a test fallback, not the deployment database."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.observability.tracing import begin_db_span, end_db_span


def make_engine(database_url: str) -> Engine:
    """Create an engine. `postgresql://` is rewritten to the installed psycopg 3 driver.

    LangGraph's checkpointer still receives the original libpq URL.
    """
    url = _sqlalchemy_url(database_url)
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 5
    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=not url.startswith("sqlite"),
        connect_args=connect_args,
    )
    _instrument_engine(engine)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def _instrument_engine(engine: Engine) -> None:
    if getattr(engine, "_rm_db_spans", False):
        return
    engine._rm_db_spans = True  # type: ignore[attr-defined]
    system = getattr(getattr(engine, "dialect", None), "name", None)
    db_system = system if system in {"sqlite", "postgresql"} else "other"

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn: Any, _cursor: Any, statement: Any, _parameters: Any, _context: Any, _executemany: bool) -> None:
        operation = _sql_operation(statement if isinstance(statement, str) else "")
        conn.info["rm_db_span"] = begin_db_span(operation, db_system)

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn: Any, _cursor: Any, _statement: Any, _parameters: Any, _context: Any, _executemany: bool) -> None:
        pair = conn.info.pop("rm_db_span", None)
        if pair is not None:
            end_db_span(pair[0], pair[1])

    @event.listens_for(engine, "handle_error")
    def _error(context: Any) -> None:
        conn = getattr(context, "connection", None)
        if conn is None:
            return
        pair = conn.info.pop("rm_db_span", None)
        if pair is None:
            return
        original = getattr(context, "original_exception", None)
        error_class = type(original).__name__ if original is not None else "DatabaseError"
        end_db_span(pair[0], pair[1], error_class=error_class)


def _sql_operation(statement: str) -> str:
    token = "".join(char for char in statement.lstrip().split(" ", 1)[0].upper() if char.isalpha())
    if token in {"SELECT", "INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT", "ROLLBACK", "PRAGMA", "WITH", "CREATE", "ALTER"}:
        return token
    return "OTHER"


def _sqlalchemy_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://") :]
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    return database_url


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ping(source: Engine | Callable[[], Session]) -> None:
    if isinstance(source, Engine):
        with source.connect() as conn:
            conn.execute(text("SELECT 1"))
        return
    session = source()
    try:
        session.execute(text("SELECT 1"))
    finally:
        session.close()
