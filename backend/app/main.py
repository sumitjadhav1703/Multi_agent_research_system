"""FastAPI application entrypoint for ResearchMind 2.0."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app import __version__
from backend.app.api.v1.guest import router as guest_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.mcp_reads import router as mcp_reads_router
from backend.app.api.v1.runs import router as runs_router
from backend.app.api.v1.stream import router as stream_router
from backend.app.api.v1.usage import router as usage_router
from backend.app.core.config import Settings, clear_settings_cache, get_settings
from backend.app.observability import configure_observability, emit, error_class, shutdown_observability
from backend.app.observability.middleware import RequestSpanMiddleware
from backend.app.db.engine import make_engine, make_session_factory
from backend.app.db.migrate import apply_migrations
from backend.app.graph.checkpointer import setup_postgres_checkpointer
from backend.app.jobs.consumer import QueueConsumer, consumer_enabled
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.executor import LifespanGraphExecutor
from backend.app.jobs.lease import recover_expired_leases
from backend.app.jobs.retention import run_retention_pass
from backend.app.jobs.turnstile import build_turnstile_verifier

logger = logging.getLogger(__name__)


# Retry schedule for a database that was not reachable at boot (Neon cold wake).
_DB_INIT_BACKOFF_SECONDS = 5.0
_DB_INIT_BACKOFF_MAX_SECONDS = 60.0


def _emit_failure(event: str, exc: BaseException) -> None:
    emit(event, {"error.class": error_class(exc)}, level=logging.ERROR)


def _dispose_engine(engine: object) -> None:
    dispose = getattr(engine, "dispose", None)
    if not callable(dispose):
        return
    try:
        dispose()
    except Exception as exc:
        _emit_failure("database.engine_dispose_failed", exc)


def _startup_retention(session_factory: Callable[[], Any], settings: Settings) -> None:
    """Best-effort purge. Failure must not discard a database that is already up."""
    session = None
    try:
        session = session_factory()
        run_retention_pass(
            session,
            retention_days=settings.data_retention_days,
            batch_size=settings.data_retention_batch_size,
        )
        session.commit()
    except Exception as exc:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        _emit_failure("retention.startup_failed", exc)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                _emit_failure("retention.startup_failed", exc)


def _mark_database_unavailable(app: FastAPI, engine: object | None, exc: BaseException) -> None:
    _emit_failure("database.startup_failed", exc)
    app.state.database_startup_error = "database_unavailable"
    app.state.session_factory = None
    app.state.postgres_url = None
    failed = getattr(app.state, "engine", None) or engine
    app.state.engine = None
    if failed is not None:
        _dispose_engine(failed)


def _start_queue_consumer(app: FastAPI, settings) -> QueueConsumer | None:
    factory = getattr(app.state, "session_factory", None)
    if factory is None or not consumer_enabled(app.state, settings.queue_consumer_enabled):
        return None
    executor = getattr(app.state, "executor", None)
    if executor is None:
        executor = LifespanGraphExecutor(settings, getattr(app.state, "postgres_url", None))
    consumer = QueueConsumer(
        session_factory=factory,
        executor=executor,
        worker_id=settings.worker_id,
        lease_seconds=settings.job_lease_seconds,
        heartbeat_seconds=settings.job_heartbeat_seconds,
        poll_seconds=settings.queue_poll_seconds,
        idle_poll_seconds=settings.queue_idle_poll_seconds,
        retention_enabled=settings.data_retention_enabled,
        retention_days=settings.data_retention_days,
        retention_interval_seconds=settings.data_retention_interval_seconds,
        retention_batch_size=settings.data_retention_batch_size,
    )
    try:
        consumer.start()
    except Exception as exc:
        _emit_failure("queue.consumer_start_failed", exc)
        try:
            consumer.stop()
        except Exception as stop_exc:
            _emit_failure("queue.consumer_stop_failed", stop_exc)
        app.state.consumer = None
        return None
    app.state.consumer = consumer
    return consumer


def _recover_leases(session_factory) -> None:
    session = session_factory()
    try:
        recover_expired_leases(session)
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            session.close()
        except Exception as close_exc:
            _emit_failure("database.session_close_failed", close_exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Non-DB setup only on the critical path. Yield ASAP so Uvicorn can bind
    # and serve /docs + /health/live while Neon/Render Free wake in the background.
    # Invalid settings (including CORS_ORIGINS) still fail closed. Database,
    # checkpointer, retention, and consumer failures are logged by class and
    # must not stop Uvicorn from serving /health/live.
    configure_observability()
    clear_settings_cache()
    settings = get_settings()
    app.state.settings = settings
    app.state.database_startup_error = None
    if getattr(app.state, "turnstile_verifier", None) is None:
        app.state.turnstile_verifier = build_turnstile_verifier(
            secret=settings.turnstile_secret_key,
            verify_url=settings.turnstile_verify_url,
            cors_origins=settings.cors_origin_list,
        )

    owns_engine = False
    consumer: QueueConsumer | None = None
    init_task: asyncio.Task | None = None

    async def _init_database() -> bool:
        nonlocal owns_engine, consumer
        engine = None
        try:
            engine = make_engine(settings.database_url or "")
            # Sync SQLAlchemy work off the event loop so /docs stays responsive.
            await asyncio.to_thread(apply_migrations, engine)
            app.state.engine = engine
            app.state.session_factory = make_session_factory(engine)
            owns_engine = True
            if (settings.database_url or "").startswith(("postgres://", "postgresql://")):
                await setup_postgres_checkpointer(settings.database_url or "", timeout_seconds=30.0)
                app.state.postgres_url = settings.database_url
            await asyncio.to_thread(_recover_leases, app.state.session_factory)
            app.state.database_startup_error = None
        except Exception as exc:
            owns_engine = False
            _mark_database_unavailable(app, engine, exc)
            return False
        finally:
            app.state.database_starting = False
        # Best-effort only; periodic retention still runs inside QueueConsumer.
        if settings.data_retention_enabled and app.state.session_factory is not None:
            await asyncio.to_thread(_startup_retention, app.state.session_factory, settings)
        consumer = _start_queue_consumer(app, settings)
        return True

    async def _init_until_ready() -> None:
        # A boot-time failure must not leave the database unavailable forever:
        # liveness stays 200, so the platform would never restart the service.
        delay = _DB_INIT_BACKOFF_SECONDS
        while not await _init_database():
            await asyncio.sleep(delay)
            delay = min(delay * 2, _DB_INIT_BACKOFF_MAX_SECONDS)

    injected = getattr(app.state, "session_factory", None) is not None
    if injected:
        # Tests and special hosts inject a factory before lifespan; start consumer only.
        consumer = _start_queue_consumer(app, settings)
        app.state.database_starting = False
    elif settings.database_configured:
        app.state.database_starting = True
        init_task = asyncio.create_task(_init_until_ready(), name="researchmind-db-init")
    else:
        app.state.database_starting = False

    yield

    if init_task is not None and not init_task.done():
        init_task.cancel()
        with suppress(asyncio.CancelledError):
            await init_task
    elif init_task is not None:
        with suppress(Exception):
            await init_task
    if consumer is not None:
        consumer.stop()
    elif getattr(app.state, "consumer", None) is not None:
        app.state.consumer.stop()
    engine = getattr(app.state, "engine", None)
    if owns_engine and engine is not None:
        engine.dispose()
    # Last, so shutdown-time spans and logs from the consumer still flush.
    shutdown_observability()


def install_cors(application: FastAPI) -> None:
    """Allow only origins named in CORS_ORIGINS. No wildcard and no credentialed cookies."""
    origins = get_settings().cors_origin_list
    if not origins:
        return
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Last-Event-ID", "Idempotency-Key"],
        max_age=600,
    )


def create_app() -> FastAPI:
    application = FastAPI(
        title="ResearchMind API",
        version=__version__,
        description="ResearchMind 2.0 backend — student demo, not a production SLA.",
        lifespan=lifespan,
    )
    application.add_middleware(RequestSpanMiddleware)
    install_cors(application)
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(guest_router, prefix="/api/v1")
    application.include_router(runs_router, prefix="/api/v1")
    application.include_router(mcp_reads_router, prefix="/api/v1")
    application.include_router(stream_router, prefix="/api/v1")
    application.include_router(usage_router, prefix="/api/v1")

    @application.exception_handler(JobServiceError)
    async def _job_error(_request: Request, exc: JobServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    @application.get("/")
    @application.head("/", include_in_schema=False)
    def root() -> dict[str, str]:
        # Render probes HEAD / during port detection; 405 confused cold starts.
        return {"service": "researchmind", "version": __version__}

    return application


app = create_app()
