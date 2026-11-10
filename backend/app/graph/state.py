"""LangGraph state for one research run.

Domain objects are stored as plain dicts so the in-memory checkpointer can
serialize them. Pydantic validation happens at node boundaries.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

CONFIG_VERSION = "m2-graph-v1"


class ResearchState(TypedDict, total=False):
    run_id: str
    owner_id: str
    topic: str
    created_at: str
    config_version: str
    subquestions: list[dict[str, Any]]
    dispatch_batch: list[str]
    fetch_budgets: dict[str, int]
    dispatch_waves: Annotated[list[int], operator.add]
    worker_results: Annotated[list[dict[str, Any]], operator.add]
    sources: list[dict[str, Any]]
    passages: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    report_draft: dict[str, Any] | None
    review_feedback: str | None
    approval_status: str
    revision_count: int
    evidence_retry_count: int
    search_calls: int
    usage: dict[str, Any]
    warnings: list[str]
    errors: list[str]
    events: Annotated[list[dict[str, Any]], operator.add]
    stop_reason: str | None
    citation_report: dict[str, Any]
    needs_followup: bool
    terminal_failure: bool


def empty_usage() -> dict[str, Any]:
    return {
        "llm_calls": 0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "token_usage_complete": True,
        "search_calls": 0,
        "elapsed_ms": None,
        "estimated_cost_usd": None,
    }


def initial_state(*, topic: str, run_id: str, owner_id: str, created_at: str) -> ResearchState:
    return {
        "run_id": run_id,
        "owner_id": owner_id,
        "topic": topic,
        "created_at": created_at,
        "config_version": CONFIG_VERSION,
        "subquestions": [],
        "dispatch_batch": [],
        "fetch_budgets": {},
        "dispatch_waves": [],
        "worker_results": [],
        "sources": [],
        "passages": [],
        "claims": [],
        "contradictions": [],
        "report_draft": None,
        "review_feedback": None,
        "approval_status": "draft",
        "revision_count": 0,
        "evidence_retry_count": 0,
        "search_calls": 0,
        "usage": empty_usage(),
        "warnings": [],
        "errors": [],
        "events": [],
        "stop_reason": None,
        "citation_report": {},
        "needs_followup": False,
        "terminal_failure": False,
    }
