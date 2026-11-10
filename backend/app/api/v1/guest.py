"""Guest identity issuance. The raw token is returned once and is not stored."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.app.api.v1.deps import call_db, current_settings, current_turnstile, get_session
from backend.app.jobs.quota import issue_guest_identity

router = APIRouter(tags=["identity"])


class GuestIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    turnstile_token: str


@router.post("/guest-identities", status_code=201)
def create_guest_identity(
    body: GuestIdentityRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> JSONResponse:
    settings = current_settings(request)
    verifier = current_turnstile(request)
    def _issue() -> str:
        return issue_guest_identity(
            session,
            verifier=verifier,
            turnstile_token=body.turnstile_token,
            # No remoteip: it is optional for siteverify, and behind the proxy
            # (forwarded-allow-ips='*') the client address is spoofable.
            remote_ip=None,
            ttl_hours=settings.guest_token_ttl_hours,
        )

    token = call_db(_issue)
    return JSONResponse(
        status_code=201,
        content={"guest_token": token, "token_type": "bearer"},
        headers={"Cache-Control": "no-store"},
    )
