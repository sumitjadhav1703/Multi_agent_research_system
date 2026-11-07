"""FastAPI application entrypoint for ResearchMind 2.0."""
from __future__ import annotations

from contextlib import asynccontextmanager

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
from backend.app.core.config import clear_settings_cache, get_settings
from backend.app.observability import configure_observability, shutdown_observability
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed on invalid free-only config before serving traffic.
    configure_observability()
    clear_settings_cache()
    settings = get_settings()
    app.state.settings = settings
    if getattr(app.state, "turnstile_verifier", None) is None:
        app.state.turnstile_verifier = build_turnstile_verifier(
            secret=settings.turnstile_secret_key,
            verify_url=settings.turnstile_verify_url,
        )
    owns_engine = False
    if getattr(app.state, "session_factory", None) is None and settings.database_configured:
        try:
            engine = make_engine(settings.database_url or "")
            apply_migrations(engine)
            app.state.engine = engine
            app.state.session_factory = make_session_factory(engine)
            owns_engine = True
            if (settings.database_url or "").startswith(("postgres://", "postgresql://")):
                await setup_postgres_checkpointer(settings.database_url or "")
                app.state.postgres_url = settings.database_url
            session = app.state.session_factory()
            try:
                recover_expired_leases(session)
                if settings.data_retention_enabled:
                    run_retention_pass(
                        session,
                        retention_days=settings.data_retention_days,
                        batch_size=settings.data_retention_batch_size,
                    )
                session.commit()
            finally:
                session.close()
        except Exception:
            app.state.database_startup_error = "database_unavailable"
            app.state.session_factory = None
    consumer = None
    factory = getattr(app.state, "session_factory", None)
    if factory is not None and consumer_enabled(app.state, settings.queue_consumer_enabled):
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
            retention_enabled=settings.data_retention_enabled,
            retention_days=settings.data_retention_days,
            retention_interval_seconds=settings.data_retention_interval_seconds,
            retention_batch_size=settings.data_retention_batch_size,
        )
        consumer.start()
        app.state.consumer = consumer
    yield
    shutdown_observability()
    if consumer is not None:
        consumer.stop()
    engine = getattr(app.state, "engine", None)
    if owns_engine and engine is not None:
        engine.dispose()


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
    def root() -> dict[str, str]:
        return {"service": "researchmind", "version": __version__}

    return application


app = create_app()
