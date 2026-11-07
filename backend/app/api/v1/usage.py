"""Safe quota view. No tokens, hashes, or provider secrets."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.v1.deps import bearer_token, call_db, current_settings, get_session
from backend.app.api.v1.runs import server_budgets
from backend.app.jobs.quota import identity_from_token, usage_snapshot

router = APIRouter(tags=["usage"])


@router.get("/me/usage")
def my_usage(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    settings = current_settings(request)
    identity = identity_from_token(session, token)
    return call_db(
        lambda: usage_snapshot(
            session,
            identity.id,
            max_active=settings.global_max_active_runs,
            daily_cap=settings.global_daily_run_cap,
            budgets=server_budgets(settings),
        )
    )
