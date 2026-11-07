"""Compile the bounded evidence-first StateGraph."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.app.graph.checkpointer import build_checkpointer
from backend.app.graph.context import GraphContext
from backend.app.graph.nodes import (
    citation_node,
    complete_node,
    evidence_gate_node,
    extract_claims_node,
    fail_node,
    human_review_node,
    merge_node,
    plan_node,
    route_after_citations,
    route_after_gate,
    route_after_merge,
    route_after_plan,
    route_after_review,
    route_after_schedule,
    route_after_validate,
    schedule_node,
    validate_node,
    verify_node,
    worker_node,
    write_node,
)
from backend.app.graph.state import ResearchState
from backend.app.observability import traced_graph_node


def build_research_graph() -> StateGraph:
    builder = StateGraph(ResearchState, context_schema=GraphContext)
    builder.add_node("validate", traced_graph_node("validate", validate_node))
    builder.add_node("plan", traced_graph_node("plan", plan_node))
    builder.add_node("schedule", traced_graph_node("schedule", schedule_node))
    builder.add_node("worker", traced_graph_node("worker", worker_node))
    builder.add_node("merge", traced_graph_node("merge", merge_node))
    builder.add_node("extract_claims", traced_graph_node("extract_claims", extract_claims_node))
    builder.add_node("verify", traced_graph_node("verify", verify_node))
    builder.add_node("evidence_gate", traced_graph_node("evidence_gate", evidence_gate_node))
    builder.add_node("write", traced_graph_node("write", write_node))
    builder.add_node("validate_citations", traced_graph_node("validate_citations", citation_node))
    builder.add_node("human_review", traced_graph_node("human_review", human_review_node))
    builder.add_node("complete", traced_graph_node("complete", complete_node))
    builder.add_node("fail", traced_graph_node("fail", fail_node))

    builder.add_edge(START, "validate")
    builder.add_conditional_edges("validate", route_after_validate, ["plan", "fail"])
    builder.add_conditional_edges("plan", route_after_plan, ["schedule", "fail"])
    builder.add_conditional_edges("schedule", route_after_schedule, ["worker", "extract_claims"])
    builder.add_edge("worker", "merge")
    builder.add_conditional_edges("merge", route_after_merge, ["schedule", "extract_claims"])
    builder.add_edge("extract_claims", "verify")
    builder.add_edge("verify", "evidence_gate")
    builder.add_conditional_edges("evidence_gate", route_after_gate, ["schedule", "write", "fail"])
    builder.add_edge("write", "validate_citations")
    builder.add_conditional_edges("validate_citations", route_after_citations, ["human_review", "fail"])
    builder.add_conditional_edges("human_review", route_after_review, ["write", "complete"])
    builder.add_edge("complete", END)
    builder.add_edge("fail", END)
    return builder


def compile_research_graph(checkpointer=None):
    saver = checkpointer if checkpointer is not None else build_checkpointer("memory")
    return build_research_graph().compile(checkpointer=saver)
