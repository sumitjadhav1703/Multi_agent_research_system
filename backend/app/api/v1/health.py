"""Liveness and readiness. Readiness pings the database when one is configured."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.db.engine import make_engine, ping

router = APIRouter(tags=["health"])


@router.get("/health/live")
@router.head("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request) -> JSONResponse:
    settings = get_settings()
    body: dict[str, object] = {
        "status": "ready",
        "app_env": settings.app_env,
        "allow_paid_models": settings.allow_paid_models,
        "use_mock_provider": settings.use_mock_provider,
        "roles": sorted(settings.role_models().keys()),
        "allowlist_size": len(settings.allowlist),
        "database": "not_configured",
    }
    if getattr(request.app.state, "database_startup_error", None):
        body["status"] = "not_ready"
        body["database"] = "unavailable"
        return JSONResponse(status_code=503, content=body)
    if getattr(request.app.state, "database_starting", False):
        # Lifespan already yielded; Neon may still be waking. Live/docs stay up.
        body["status"] = "not_ready"
        body["database"] = "starting"
        return JSONResponse(status_code=503, content=body)
    factory = getattr(request.app.state, "session_factory", None)
    if factory is not None or settings.database_configured:
        try:
            if factory is not None:
                ping(factory)
            else:
                engine = make_engine(settings.database_url or "")
                try:
                    ping(engine)
                finally:
                    engine.dispose()
            body["database"] = "ok"
        except Exception:
            body["status"] = "not_ready"
            body["database"] = "unavailable"
            return JSONResponse(status_code=503, content=body)
    return JSONResponse(status_code=200, content=body)
