"""Research graph nodes. Workers return isolated results; merge owns the ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Send, interrupt

from backend.app.graph.context import GraphContext
from backend.app.graph.events import emit
from backend.app.graph.model_io import complete_json
from backend.app.graph.prompts import (
    PLANNER_SYSTEM,
    RESEARCHER_SYSTEM,
    VERIFIER_SYSTEM,
    WRITER_SYSTEM,
    untrusted_block,
)
from backend.app.graph.state import ResearchState, empty_usage
from backend.app.research.evidence import (
    contradictions_for,
    enforce_claim_assessments,
    finalize_ledger,
    latest_worker_status,
    merge_worker_outputs,
    new_result_id,
    run_worker_retrieval,
)
from backend.app.research.retrieval import clean_query
from backend.app.schemas.research import (
    EVIDENCE_WORDING,
    Claim,
    Passage,
    ReportDraft,
    ReportSection,
    ResearchPlan,
    SourceRecord,
    SubQuestion,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    topic = (state.get("topic") or "").strip()
    if not topic or len(topic) > limits.max_topic_chars:
        return {
            "topic": topic,
            "stop_reason": "invalid_request",
            "approval_status": "failed",
            "errors": ["Topic must be between 1 and 500 characters."],
        }
    return {
        "topic": topic,
        "events": [
            emit(
                "run.accepted",
                "validate",
                {"run_id": state.get("run_id"), "config_version": state.get("config_version")},
            )
        ],
    }


def route_after_validate(state: ResearchState) -> str:
    if state.get("stop_reason"):
        return "fail"
    return "plan"


def plan_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    events = [emit("planner.started", "plan", {})]
    parsed, usage, error = complete_json(
        runtime.context.model_client,
        state.get("usage"),
        role="planner",
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": state.get("topic") or ""},
        ],
        max_tokens=700,
        max_model_calls=limits.max_model_calls,
    )
    if parsed is None:
        stop = _planner_stop(error)
        return {
            "usage": usage,
            "stop_reason": stop,
            "approval_status": "failed",
            "errors": [error or stop],
            "events": events + [emit("warning", "plan", {"code": stop})],
        }
    raw_items = parsed.get("subquestions")
    if not isinstance(raw_items, list) or not raw_items:
        return {
            "usage": usage,
            "stop_reason": "planner_output_invalid",
            "approval_status": "failed",
            "errors": ["planner_output_invalid"],
            "events": events + [emit("warning", "plan", {"code": "planner_output_invalid"})],
        }
    subquestions: list[dict[str, Any]] = []
    for item in raw_items[: limits.max_subquestions]:
        if not isinstance(item, dict):
            continue
        question = clean_query(str(item.get("question") or ""), 300)
        if not question:
            continue
        query = clean_query(str(item.get("search_query") or question))
        subquestions.append(
            SubQuestion(
                subquestion_id=f"sq{len(subquestions) + 1}",
                question=question,
                search_query=query or question,
                expected_evidence=clean_query(str(item.get("expected_evidence") or ""), 240),
            ).model_dump()
        )
    if not subquestions:
        return {
            "usage": usage,
            "stop_reason": "planner_output_invalid",
            "approval_status": "failed",
            "errors": ["planner_output_invalid"],
            "events": events + [emit("warning", "plan", {"code": "planner_output_invalid"})],
        }
    warnings = list(state.get("warnings") or [])
    if len(raw_items) > limits.max_subquestions:
        warnings.append(f"Planner output truncated to {limits.max_subquestions} subquestions.")
    plan = ResearchPlan(topic=state.get("topic") or "", subquestions=[SubQuestion.model_validate(sq) for sq in subquestions])
    events.append(
        emit("planner.completed", "plan", {"subquestions": len(subquestions), "truncated": len(raw_items) > len(subquestions)})
    )
    return {
        "research_plan": plan.model_dump(),
        "subquestions": subquestions,
        "usage": usage,
        "warnings": _unique(warnings),
        "events": events,
    }


def route_after_plan(state: ResearchState) -> str:
    if state.get("stop_reason"):
        return "fail"
    return "schedule"


def schedule_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    subquestions = [dict(item) for item in state.get("subquestions") or []]
    pending = [item for item in subquestions if item.get("status") == "pending"]
    remaining_search = limits.max_search_calls - int(state.get("search_calls") or 0)
    slots = limits.max_sources - len(state.get("sources") or [])
    batch: list[str] = []
    budgets: dict[str, int] = {}
    left_slots = slots
    left_search = remaining_search
    for item in pending:
        if len(batch) >= limits.max_parallel_workers or left_search <= 0 or left_slots <= 0:
            break
        take = min(limits.max_fetches_per_worker, left_slots)
        batch.append(str(item["subquestion_id"]))
        budgets[str(item["subquestion_id"])] = take
        left_slots -= take
        left_search -= 1
    batch_ids = set(batch)
    updated: list[dict[str, Any]] = []
    skipped = False
    for item in subquestions:
        if item.get("subquestion_id") in batch_ids:
            updated.append({**item, "status": "inflight"})
        elif item.get("status") == "pending" and not batch and (remaining_search <= 0 or slots <= 0):
            updated.append({**item, "status": "skipped"})
            skipped = True
        else:
            updated.append(item)
    warnings = list(state.get("warnings") or [])
    if skipped:
        warnings.append("Search or source budget exhausted.")
    events = []
    if batch:
        events.append(emit("worker.started", "schedule", {"count": len(batch), "subquestion_ids": batch}))
    return {
        "subquestions": updated,
        "dispatch_batch": batch,
        "fetch_budgets": budgets,
        "dispatch_waves": [len(batch)] if batch else [],
        "warnings": _unique(warnings),
        "events": events,
    }


def route_after_schedule(state: ResearchState) -> str | list[Send]:
    batch = list(state.get("dispatch_batch") or [])
    if not batch:
        return "extract_claims"
    budgets = state.get("fetch_budgets") or {}
    sends: list[Send] = []
    for item in state.get("subquestions") or []:
        subquestion_id = str(item.get("subquestion_id"))
        if subquestion_id in batch and item.get("status") == "inflight":
            sends.append(
                Send(
                    "worker",
                    {
                        "task": item,
                        "topic": state.get("topic"),
                        "run_id": state.get("run_id"),
                        "fetch_budget": int(budgets.get(subquestion_id, 0)),
                    },
                )
            )
    return sends or "extract_claims"


def worker_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    task = state["task"]  # type: ignore[index]
    subquestion_id = str(task["subquestion_id"])
    result = run_worker_retrieval(
        result_id=new_result_id(subquestion_id),
        subquestion_id=subquestion_id,
        question=str(task.get("question") or ""),
        search_query=clean_query(str(task.get("search_query") or task.get("question") or "")),
        fetch_budget=int(state.get("fetch_budget") or 0),
        retrieval=runtime.context.retrieval,
        limits=runtime.context.limits,
        retrieved_at=utc_now(),
    )
    events = []
    for source in result.sources:
        events.append(
            emit(
                "source.discovered",
                "worker",
                {
                    "source_id": source.source_id,
                    "url": source.canonical_url,
                    "extraction_method": source.extraction_method,
                    "subquestion_id": subquestion_id,
                },
            )
        )
        events.append(
            emit(
                "source.extracted",
                "worker",
                {"source_id": source.source_id, "content_hash": source.content_hash[:16]},
            )
        )
    if result.status == "failed":
        events.append(emit("worker.failed", "worker", {"subquestion_id": subquestion_id, "error": result.error}))
    else:
        events.append(
            emit(
                "worker.completed",
                "worker",
                {"subquestion_id": subquestion_id, "status": result.status, "sources": len(result.sources)},
            )
        )
    return {"worker_results": [result.model_dump()], "events": events}


def merge_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    sources, passages, search_calls, warnings = merge_worker_outputs(list(state.get("worker_results") or []))
    if len(sources) > limits.max_sources:
        dropped = sources[limits.max_sources :]
        sources = sources[: limits.max_sources]
        kept_ids = {source["source_id"] for source in sources}
        passages = [passage for passage in passages if passage["source_id"] in kept_ids]
        warnings.extend(f"source cap dropped:{source['source_id']}" for source in dropped)
    statuses = latest_worker_status(list(state.get("worker_results") or []))
    updated = []
    for item in state.get("subquestions") or []:
        subquestion_id = str(item.get("subquestion_id"))
        if item.get("status") == "inflight" and subquestion_id in statuses:
            updated.append({**item, "status": "done", "worker_status": statuses[subquestion_id]})
        else:
            updated.append(item)
    usage = dict(state.get("usage") or empty_usage())
    usage["search_calls"] = search_calls
    usage["estimated_cost_usd"] = None
    return {
        "sources": sources,
        "passages": passages,
        "subquestions": updated,
        "search_calls": search_calls,
        "dispatch_batch": [],
        "usage": usage,
        "warnings": _unique(list(state.get("warnings") or []) + warnings),
    }


def route_after_merge(state: ResearchState) -> str:
    if any(item.get("status") == "pending" for item in state.get("subquestions") or []):
        return "schedule"
    return "extract_claims"


def extract_claims_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    passages = [Passage.model_validate(item) for item in state.get("passages") or []]
    events = [emit("evidence.extracted", "extract_claims", {"count": len(passages)})]
    if not passages:
        return {"claims": [], "contradictions": [], "events": events}
    known = {passage.evidence_id for passage in passages}
    listing = ["Evidence IDs you may cite:"]
    for passage in passages[:6]:
        listing.append(f"ID={passage.evidence_id} URL={passage.url}")
        listing.append(untrusted_block(passage.quote))
    parsed, usage, error = complete_json(
        runtime.context.model_client,
        state.get("usage"),
        role="researcher",
        messages=[
            {"role": "system", "content": RESEARCHER_SYSTEM},
            {"role": "user", "content": "\n".join(listing)},
        ],
        max_tokens=800,
        max_model_calls=limits.max_model_calls,
    )
    proposals: list[Claim] = []
    warnings = list(state.get("warnings") or [])
    if error:
        warnings.append(f"claim extraction failed:{error}")
    for item in (parsed or {}).get("claims") or []:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text") or "").split())[:500]
        evidence_ids = [str(eid) for eid in item.get("evidence_ids") or [] if str(eid) in known]
        if not text or not evidence_ids:
            continue
        proposals.append(
            Claim(
                claim_id=f"cl{len(proposals) + 1}",
                text=text,
                evidence_ids=evidence_ids,
                status="insufficient",
                verification_reason="Awaiting verification.",
            )
        )
    return {
        "claims": [claim.model_dump() for claim in proposals],
        "contradictions": [],
        "usage": usage if parsed is not None or error else state.get("usage"),
        "warnings": _unique(warnings),
        "events": events,
    }


def verify_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    claims = [Claim.model_validate(item) for item in state.get("claims") or []]
    passages = [Passage.model_validate(item) for item in state.get("passages") or []]
    if not claims:
        return {"events": [emit("claim.verified", "verify", {"count": 0})]}
    listing = ["Claims and the only passages you may use:"]
    for claim in claims:
        listing.append(f"CLAIM {claim.claim_id}: {claim.text}")
        listing.append(f"EVIDENCE_IDS {', '.join(claim.evidence_ids)}")
    by_passage = {passage.evidence_id: passage for passage in passages}
    for claim in claims:
        for evidence_id in claim.evidence_ids:
            passage = by_passage.get(evidence_id)
            if passage:
                listing.append(f"QUOTE {passage.evidence_id}")
                listing.append(untrusted_block(passage.quote))
    parsed, usage, error = complete_json(
        runtime.context.model_client,
        state.get("usage"),
        role="verifier",
        messages=[
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user", "content": "\n".join(listing)},
        ],
        max_tokens=800,
        max_model_calls=limits.max_model_calls,
    )
    decisions = {}
    if parsed:
        for row in parsed.get("results") or []:
            if isinstance(row, dict) and row.get("claim_id"):
                decisions[str(row["claim_id"])] = row
    updated: list[Claim] = []
    for claim in claims:
        row = decisions.get(claim.claim_id)
        if row:
            status = row.get("status")
            if status not in {"supported", "contradictory", "insufficient"}:
                status = "insufficient"
            reason = str(row.get("verification_reason") or "Verifier returned no rationale.")[:500]
            claim = claim.model_copy(update={"status": status, "verification_reason": reason})
        else:
            claim = claim.model_copy(
                update={
                    "status": "insufficient",
                    "verification_reason": "Verifier unavailable. Model opinion was not used as evidence.",
                }
            )
        updated.append(claim)
    updated, notes = enforce_claim_assessments(updated, passages)
    contradictions = contradictions_for(updated)
    events = []
    for claim in updated:
        event_type = "claim.conflicted" if claim.status == "contradictory" else "claim.verified"
        events.append(emit(event_type, "verify", {"claim_id": claim.claim_id, "status": claim.status}))
    warnings = list(state.get("warnings") or [])
    if error:
        warnings.append(f"verifier failed:{error}")
    warnings.extend(notes)
    return {
        "claims": [claim.model_dump() for claim in updated],
        "contradictions": [item.model_dump() for item in contradictions],
        "usage": usage,
        "warnings": _unique(warnings),
        "events": events,
    }


def evidence_gate_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    claims = list(state.get("claims") or [])
    if any(claim.get("status") == "supported" for claim in claims):
        return {"needs_followup": False, "terminal_failure": False}
    retry = int(state.get("evidence_retry_count") or 0)
    searches = int(state.get("search_calls") or 0)
    statuses = latest_worker_status(list(state.get("worker_results") or []))
    all_failed = bool(statuses) and all(value == "failed" for value in statuses.values()) and not state.get("passages")
    can_retry = (
        retry < limits.max_evidence_retries
        and searches < limits.max_search_calls
        and not any(item.get("kind") == "followup" for item in state.get("subquestions") or [])
    )
    if can_retry:
        seed = next(iter(state.get("subquestions") or []), None)
        question = str((seed or {}).get("question") or state.get("topic") or "")
        follow = SubQuestion(
            subquestion_id="sq_followup",
            question=question,
            search_query=clean_query(f"{question} additional independent source"),
            expected_evidence="an independent source for the same question",
            status="pending",
            kind="followup",
        )
        return {
            "subquestions": list(state.get("subquestions") or []) + [follow.model_dump()],
            "evidence_retry_count": retry + 1,
            "needs_followup": True,
            "terminal_failure": False,
            "warnings": _unique(list(state.get("warnings") or []) + ["Evidence gap triggered one follow-up search."]),
            "events": [emit("warning", "evidence_gate", {"code": "evidence_retry"})],
        }
    if all_failed:
        return {
            "needs_followup": False,
            "terminal_failure": True,
            "stop_reason": "retrieval_failed",
            "approval_status": "failed",
            "errors": _unique(list(state.get("errors") or []) + ["retrieval_failed"]),
        }
    return {
        "needs_followup": False,
        "terminal_failure": False,
        "warnings": _unique(
            list(state.get("warnings") or []) + ["Evidence remains insufficient after the bounded retry."]
        ),
    }


def route_after_gate(state: ResearchState) -> str:
    if state.get("terminal_failure"):
        return "fail"
    if state.get("needs_followup"):
        return "schedule"
    return "write"


def write_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    claims = [Claim.model_validate(item) for item in state.get("claims") or []]
    events = [emit("writer.started", "write", {"revision_count": state.get("revision_count") or 0})]
    feedback = (state.get("review_feedback") or "").strip()
    lines = ["Verified claims:"]
    if not claims:
        lines.append("No claims were assessed.")
    for claim in claims:
        lines.append(
            f"{claim.claim_id} status={claim.status} evidence={','.join(claim.evidence_ids) or 'none'} text={claim.text}"
        )
    if feedback and int(state.get("revision_count") or 0) >= 1:
        lines.append("Human revision notes (style only; do not add facts):")
        lines.append(feedback)
    parsed, usage, error = complete_json(
        runtime.context.model_client,
        state.get("usage"),
        role="writer",
        messages=[
            {"role": "system", "content": WRITER_SYSTEM},
            {"role": "user", "content": "\n".join(lines)},
        ],
        max_tokens=900,
        max_model_calls=limits.max_model_calls,
    )
    warnings = list(state.get("warnings") or [])
    if parsed is None:
        warnings.append(f"writer fallback:{error or 'invalid_output'}")
        report = ReportDraft(title=(state.get("topic") or "Research")[:180], sections=[])
    else:
        report = _report_from_payload(parsed, state.get("topic") or "Research")
    return {
        "report_draft": report.model_dump(),
        "usage": usage,
        "warnings": _unique(warnings),
        "events": events,
        "approval_status": "draft",
    }


def citation_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    del runtime
    claims = [Claim.model_validate(item) for item in state.get("claims") or []]
    passages = [Passage.model_validate(item) for item in state.get("passages") or []]
    sources = [SourceRecord.model_validate(item) for item in state.get("sources") or []]
    draft = state.get("report_draft") or {"title": state.get("topic") or "Research", "sections": []}
    report = ReportDraft.model_validate(draft)
    claims, report, meta = finalize_ledger(claims, passages, sources, report)
    ok = bool(meta.get("ok"))
    event_type = "writer.completed" if ok else "warning"
    return {
        "claims": [claim.model_dump() for claim in claims],
        "report_draft": report.model_dump(),
        "contradictions": [item.model_dump() for item in contradictions_for(claims)],
        "citation_report": meta,
        "approval_status": "awaiting_review" if ok else "failed",
        "stop_reason": None if ok else "citation_failed",
        "events": [emit(event_type, "validate_citations", {"ok": ok, "repairs": len(meta.get("repairs") or [])})],
    }


def route_after_citations(state: ResearchState) -> str:
    if (state.get("citation_report") or {}).get("ok"):
        return "human_review"
    return "fail"


def human_review_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    limits = runtime.context.limits
    revision_count = int(state.get("revision_count") or 0)
    decision = interrupt(
        {
            "type": "review.awaiting",
            "run_id": state.get("run_id"),
            "approval_status": "awaiting_review",
            "revision_count": revision_count,
            "revisions_remaining": max(0, limits.max_revisions - revision_count),
            "wording": EVIDENCE_WORDING,
            "report": _compact_report(state.get("report_draft") or {}),
            "claims": [
                {
                    "claim_id": claim.get("claim_id"),
                    "status": claim.get("status"),
                    "evidence_ids": claim.get("evidence_ids") or [],
                }
                for claim in (state.get("claims") or [])[:12]
            ],
        }
    )
    if not isinstance(decision, dict):
        decision = {}
    action = decision.get("action")
    comments = str(decision.get("comments") or "")[:2000]
    events = [emit("review.resumed", "human_review", {"action": action if isinstance(action, str) else "invalid"})]
    if action == "approve":
        return {
            "approval_status": "approved",
            "review_feedback": comments,
            "stop_reason": "approved",
            "events": events,
        }
    if action == "reject":
        return {
            "approval_status": "rejected",
            "review_feedback": comments,
            "stop_reason": "human_rejected",
            "events": events,
        }
    if action == "revise":
        if revision_count >= limits.max_revisions:
            return {
                "approval_status": "rejected",
                "review_feedback": comments,
                "stop_reason": "revision_limit",
                "warnings": _unique(list(state.get("warnings") or []) + ["Revision limit reached."]),
                "events": events,
            }
        return {
            "approval_status": "revision_requested",
            "revision_count": revision_count + 1,
            "review_feedback": comments,
            "stop_reason": None,
            "events": events,
        }
    return {
        "approval_status": "rejected",
        "review_feedback": comments,
        "stop_reason": "invalid_review_action",
        "events": events,
    }


def route_after_review(state: ResearchState) -> str:
    if state.get("approval_status") == "revision_requested":
        return "write"
    return "complete"


def complete_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    del runtime
    status = state.get("approval_status") or "completed_unreviewed"
    stop = state.get("stop_reason") or status
    usage = dict(state.get("usage") or empty_usage())
    usage["search_calls"] = state.get("search_calls")
    usage["estimated_cost_usd"] = None
    return {
        "approval_status": status,
        "stop_reason": stop,
        "usage": usage,
        "events": [
            emit(
                "usage.updated",
                "complete",
                {
                    "llm_calls": usage.get("llm_calls"),
                    "search_calls": usage.get("search_calls"),
                    "estimated_cost_usd": None,
                },
            ),
            emit("run.completed", "complete", {"approval_status": status, "stop_reason": stop}),
        ],
    }


def fail_node(state: ResearchState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    del runtime
    stop = state.get("stop_reason") or "failed"
    usage = dict(state.get("usage") or empty_usage())
    usage["estimated_cost_usd"] = None
    return {
        "approval_status": "failed",
        "stop_reason": stop,
        "usage": usage,
        "events": [
            emit("run.failed", "fail", {"stop_reason": stop, "errors": list(state.get("errors") or [])}),
        ],
    }


def _planner_stop(error: str | None) -> str:
    if error == "invalid_output":
        return "planner_output_invalid"
    if error == "model_budget":
        return "model_budget"
    return "provider_failure"


def _report_from_payload(payload: dict[str, Any], fallback_title: str) -> ReportDraft:
    sections: list[ReportSection] = []
    for index, row in enumerate(payload.get("sections") or [], start=1):
        if not isinstance(row, dict):
            continue
        sections.append(
            ReportSection(
                section_id=f"sec{index}",
                heading=str(row.get("heading") or "Finding")[:120],
                body=str(row.get("body") or "")[:2000],
                evidence_ids=[str(item) for item in row.get("evidence_ids") or []],
                claim_ids=[str(item) for item in row.get("claim_ids") or []],
                kind="finding",
            )
        )
    title = str(payload.get("title") or fallback_title)[:180]
    return ReportDraft(title=title, sections=sections)


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    sections = []
    for section in (report.get("sections") or [])[:8]:
        sections.append(
            {
                "section_id": section.get("section_id"),
                "heading": section.get("heading"),
                "kind": section.get("kind"),
                "body": str(section.get("body") or "")[:400],
                "evidence_ids": section.get("evidence_ids") or [],
            }
        )
    return {"title": report.get("title"), "wording": report.get("wording"), "sections": sections}


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
