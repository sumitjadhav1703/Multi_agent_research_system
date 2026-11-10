"""Owner-scoped artifact snapshot shared by SSE and MCP read routes.

The snapshot is built from persisted rows. It is not a job event and it does
not include identity ids, bearer tokens, error detail, or provider secrets.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    EvidencePassage,
    ResearchClaim,
    ResearchReport,
    ResearchSource,
    UsageLedger,
)
from backend.app.cost_estimate import estimate_usage_cost_usd
from backend.app.schemas.research import EVIDENCE_WORDING


def sum_optional(values: list[int | None]) -> int | None:
    present = [item for item in values if isinstance(item, int) and not isinstance(item, bool)]
    if not present:
        return None
    return sum(present)


def evidence_ids(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed[:40]]


def build_snapshot(session: Session, run_id: str) -> dict[str, object]:
    report = session.scalar(
        select(ResearchReport)
        .where(ResearchReport.job_id == run_id)
        .order_by(ResearchReport.version.desc())
    )
    sources = session.scalars(select(ResearchSource).where(ResearchSource.job_id == run_id)).all()
    passages = session.scalars(select(EvidencePassage).where(EvidencePassage.job_id == run_id)).all()
    claims = session.scalars(select(ResearchClaim).where(ResearchClaim.job_id == run_id)).all()
    usage_rows = session.scalars(select(UsageLedger).where(UsageLedger.job_id == run_id)).all()
    costs = [row.estimated_cost_usd for row in usage_rows if row.estimated_cost_usd]
    report_body = None
    if report is not None and report.markdown.strip():
        report_body = {
            "version": report.version,
            "markdown": report.markdown,
            "approval_state": report.approval_state,
            "created_at": report.created_at,
        }
    return {
        "run_id": run_id,
        "wording": EVIDENCE_WORDING,
        "report": report_body,
        "sources": [
            {
                "source_id": row.source_key,
                "url": row.url,
                "canonical_url": row.canonical_url,
                "domain": row.domain,
                "title": row.title,
                "excerpt": row.excerpt,
                "extraction_method": row.extraction_method,
                "retrieved_at": row.retrieved_at,
                "content_hash": row.content_hash,
            }
            for row in sources
        ],
        "passages": [
            {
                "evidence_id": row.evidence_key,
                "source_id": row.source_key,
                "subquestion_id": row.subquestion_id,
                "quote": row.quote,
            }
            for row in passages
        ],
        "claims": [
            {
                "claim_id": row.claim_key,
                "text": row.claim_text,
                "status": row.status,
                "verification_reason": row.verification_reason,
                "evidence_ids": evidence_ids(row.evidence_ids_json),
            }
            for row in claims
        ],
        "usage": {
            "llm_calls": sum_optional([row.llm_calls for row in usage_rows]),
            "prompt_tokens": sum_optional([row.prompt_tokens for row in usage_rows]),
            "completion_tokens": sum_optional([row.completion_tokens for row in usage_rows]),
            "total_tokens": sum_optional([row.total_tokens for row in usage_rows]),
            "search_calls": sum_optional([row.search_calls for row in usage_rows]),
            "estimated_cost_usd": (
                costs[0]
                if len(costs) == 1
                else estimate_usage_cost_usd(
                    prompt_tokens=sum_optional([row.prompt_tokens for row in usage_rows]),
                    completion_tokens=sum_optional([row.completion_tokens for row in usage_rows]),
                    search_calls=sum_optional([row.search_calls for row in usage_rows]),
                )
            ),
        },
    }
