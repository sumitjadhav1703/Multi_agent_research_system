"""JSON reads used by the remote MCP tools.

These routes do not start work, do not call providers, and do not run the
research graph. Ownership matches the other run routes: a missing run and a
run owned by someone else both return 404. The evaluation summary is the
manually published harness note. It is not a quality score.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.v1.deps import bearer_token, call_db, get_session
from backend.app.api.v1.snapshot import build_snapshot
from backend.app.jobs.errors import JobServiceError
from backend.app.jobs.quota import get_owned_job, identity_from_token
from backend.app.schemas.research import EVIDENCE_WORDING

router = APIRouter(tags=["mcp-reads"])

_MAX_CITATIONS = 20
_MAX_PASSAGES = 20

# Fallback if docs/evals/published-summary.json is missing from the image.
_FALLBACK_EVALUATION_SUMMARY: dict[str, object] = {
    "published": True,
    "visibility": "authenticated",
    "measured": False,
    "dataset": "golden-v0.1",
    "dataset_cases": 32,
    "systems_compared": [],
    "frozen_source_snapshot": False,
    "run_date": "2026-11-09",
    "judge": {
        "measured": False,
        "deepeval_version": "4.3.3",
        "model": "meta/muse-spark-1.3-contributor",
        "temperature": 0,
        "scores": None,
        "note": "Published summary file was not found in this deployment.",
    },
    "deterministic": {
        "kind": "fixture_self_check",
        "system": "fixture",
        "dataset": 32,
        "runs": 20,
        "fixture_mismatches": 0,
        "unlabeled_issues": 0,
        "note": (
            "These counts check the harness and hand-built fixtures. "
            "They are not a V1 versus V2 quality table."
        ),
    },
}


def _load_published_evaluation_summary() -> dict[str, object]:
    """Read docs/evals/published-summary.json (repo checkout, or COPYed to /app/docs in Docker)."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[4] / "docs" / "evals" / "published-summary.json",
        Path.cwd() / "docs" / "evals" / "published-summary.json",
    ]
    for path in candidates:
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            continue
    return dict(_FALLBACK_EVALUATION_SUMMARY)


def _owned_snapshot(session: Session, run_id: str, token: str) -> dict[str, object]:
    identity = identity_from_token(session, token)
    get_owned_job(session, run_id, identity.id)
    return build_snapshot(session, run_id)


@router.get("/research-runs/{run_id}/report")
def get_report(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    snapshot = call_db(lambda: _owned_snapshot(session, run_id, token))
    sources = snapshot["sources"]
    citations: list[dict[str, object]] = []
    if isinstance(sources, list):
        for source in sources[:_MAX_CITATIONS]:
            if not isinstance(source, dict):
                continue
            citations.append(
                {
                    "source_id": source.get("source_id"),
                    "title": source.get("title"),
                    "url": source.get("url"),
                    "domain": source.get("domain"),
                }
            )
    return {
        "run_id": run_id,
        "wording": EVIDENCE_WORDING,
        "report": snapshot["report"],
        "citations": citations,
    }


@router.get("/research-runs/{run_id}/sources")
def list_sources(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    snapshot = call_db(lambda: _owned_snapshot(session, run_id, token))
    sources = snapshot["sources"] if isinstance(snapshot["sources"], list) else []
    return {"run_id": run_id, "sources": sources[:_MAX_CITATIONS]}


@router.get("/research-runs/{run_id}/claims/{claim_id}/evidence")
def get_claim_evidence(
    run_id: str,
    claim_id: str,
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    snapshot = call_db(lambda: _owned_snapshot(session, run_id, token))
    claims = snapshot["claims"] if isinstance(snapshot["claims"], list) else []
    claim = next((item for item in claims if isinstance(item, dict) and item.get("claim_id") == claim_id), None)
    if claim is None:
        raise JobServiceError(404, "claim_not_found", "Claim not found.")
    passages = snapshot["passages"] if isinstance(snapshot["passages"], list) else []
    wanted = set(claim.get("evidence_ids") or [])
    linked = [
        item
        for item in passages
        if isinstance(item, dict) and item.get("evidence_id") in wanted
    ][:_MAX_PASSAGES]
    missing = sorted(wanted - {item.get("evidence_id") for item in linked if isinstance(item, dict)})
    return {
        "run_id": run_id,
        "wording": EVIDENCE_WORDING,
        "claim": claim,
        "passages": linked,
        "missing_evidence_ids": missing,
    }


@router.get("/evaluation/summary")
def evaluation_summary(
    session: Annotated[Session, Depends(get_session)],
    token: Annotated[str, Depends(bearer_token)],
) -> dict[str, object]:
    """Authenticated read of the published summary. The body is not per-user."""
    call_db(lambda: identity_from_token(session, token))
    # Reload so a redeployed JSON file is visible without code edits.
    return _load_published_evaluation_summary()
