"""Request dependencies for identity and database sessions."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Header, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.turnstile import build_turnstile_verifier


def get_session(request: Request) -> Iterator[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise JobServiceError(503, "database_unavailable", "Database is unavailable.")
    try:
        session = factory()
    except SQLAlchemyError:
        raise JobServiceError(503, "database_unavailable", "Database is unavailable.") from None
    try:
        yield session
    finally:
        session.close()


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise JobServiceError(401, "unauthorized", "Guest token is missing or invalid.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise JobServiceError(401, "unauthorized", "Guest token is missing or invalid.")
    return token


def current_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if settings is not None else get_settings()


def current_turnstile(request: Request):
    verifier = getattr(request.app.state, "turnstile_verifier", None)
    if verifier is not None:
        return verifier
    settings = current_settings(request)
    verifier = build_turnstile_verifier(
        secret=settings.turnstile_secret_key,
        verify_url=settings.turnstile_verify_url,
        cors_origins=settings.cors_origin_list,
    )
    request.app.state.turnstile_verifier = verifier
    return verifier


def call_db(action):
    try:
        return action()
    except JobServiceError:
        raise
    except SQLAlchemyError:
        raise JobServiceError(503, "database_unavailable", "Database is unavailable.") from None


def wake_consumer(request: Request) -> None:
    """Tell the queue consumer there is work now; it idles on a long poll otherwise."""
    consumer = getattr(request.app.state, "consumer", None)
    if consumer is not None:
        consumer.wake()
