"""Liveness and readiness. Readiness pings the database when one is configured."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.db.engine import ping

router = APIRouter(tags=["health"])


@router.get("/health/live")
@router.head("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request) -> JSONResponse:
    # Public endpoint: status only. Config (env, allowlist, roles) stays out.
    # use_mock_provider stays because the console Usage page shows it.
    body: dict[str, object] = {
        "status": "ready",
        "use_mock_provider": get_settings().use_mock_provider,
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
    if factory is not None:
        try:
            ping(factory)
            body["database"] = "ok"
        except Exception:
            body["status"] = "not_ready"
            body["database"] = "unavailable"
            return JSONResponse(status_code=503, content=body)
    return JSONResponse(status_code=200, content=body)
