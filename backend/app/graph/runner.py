"""Start and resume one in-process research graph.

The checkpointer is in-memory. A new process cannot resume a paused review,
and a provider call that dies before its node finishes can run again.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from langgraph.types import Command
from pydantic import BaseModel, Field

from backend.app.graph.builder import compile_research_graph
from backend.app.graph.checkpointer import build_checkpointer
from backend.app.graph.context import GraphContext
from backend.app.graph.events import number_events
from backend.app.graph.limits import GraphLimits
from backend.app.graph.nodes import utc_now
from backend.app.graph.state import empty_usage, initial_state
from backend.app.observability import start_span
from backend.app.cost_estimate import refresh_estimated_cost
from backend.app.schemas.research import ReviewDecision


class RunNotPaused(RuntimeError):
    pass


class RunOutcome(BaseModel):
    run_id: str
    interrupted: bool
    interrupt_payload: dict[str, Any] | None = None
    approval_status: str
    stop_reason: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    state: dict[str, Any]
    elapsed_ms: int


class ResearchGraphRunner:
    def __init__(
        self,
        *,
        model_client: Any,
        retrieval: Any,
        limits: GraphLimits | None = None,
        checkpointer: Any | None = None,
    ):
        self.limits = (limits or GraphLimits()).clamped()
        self.context = GraphContext(
            model_client=model_client,
            retrieval=retrieval,
            limits=self.limits,
        )
        self.checkpointer = checkpointer if checkpointer is not None else build_checkpointer("memory")
        self.graph = compile_research_graph(self.checkpointer)
        self._elapsed_ms: dict[str, int] = {}

    def start(self, topic: str, *, owner_id: str = "local-owner", run_id: str | None = None) -> RunOutcome:
        run_id = run_id or uuid.uuid4().hex
        config = self._config(run_id)
        payload = initial_state(topic=topic, run_id=run_id, owner_id=owner_id, created_at=utc_now())
        return self._finish(payload, config)

    def resume(self, run_id: str, decision: ReviewDecision) -> RunOutcome:
        config = self._config(run_id)
        snapshot = self.graph.get_state(config)
        if not getattr(snapshot, "interrupts", None):
            raise RunNotPaused(f"Run {run_id} is not waiting for review.")
        return self._finish(Command(resume=decision.model_dump()), config)

    def continue_from_checkpoint(self, run_id: str) -> RunOutcome:
        """Continue a thread after the process that started it stopped.

        A model call that died before its node checkpoint can run again.
        """
        return self._finish(None, self._config(run_id))

    def peek(self, run_id: str) -> tuple[bool, bool, dict[str, Any]]:
        snapshot = self.graph.get_state(self._config(run_id))
        state = dict(getattr(snapshot, "values", None) or {})
        return bool(state), bool(_interrupt_values(snapshot)), state

    def _finish(self, payload: Any, config: dict[str, Any]) -> RunOutcome:
        run_id = config["configurable"]["thread_id"]
        with start_span("research.run", run_id=run_id) as span:
            return self._invoke(payload, config, span)

    def _invoke(self, payload: Any, config: dict[str, Any], span: Any) -> RunOutcome:
        run_id = config["configurable"]["thread_id"]
        started = time.perf_counter()
        result = self.graph.invoke(
            payload,
            config,
            context=self.context,
        )
        self._elapsed_ms[run_id] = self._elapsed_ms.get(run_id, 0) + int((time.perf_counter() - started) * 1000)
        snapshot = self.graph.get_state(config)
        interrupts = _interrupt_values(snapshot)
        if not interrupts and isinstance(result, dict):
            interrupts = _coerce_interrupt(result.get("__interrupt__"))
        state = dict(snapshot.values or {})
        usage = dict(state.get("usage") or empty_usage())
        usage["elapsed_ms"] = self._elapsed_ms[run_id]
        usage = refresh_estimated_cost(usage)
        state["usage"] = usage
        events = number_events(list(state.get("events") or []))
        payload_value = interrupts[0] if interrupts else None
        span.set(
            interrupted=payload_value is not None,
            approval_status=str(state.get("approval_status") or "unknown"),
            stop_reason=str(state.get("stop_reason") or "none"),
        )
        if payload_value is not None:
            max_id = 0
            for event in events:
                eid = event.get("event_id")
                if isinstance(eid, int) and eid > max_id:
                    max_id = eid
            events.append(
                {
                    "event_id": max_id + 1,
                    "type": "review.awaiting",
                    "node": "human_review",
                    "payload": payload_value if isinstance(payload_value, dict) else {"value": str(payload_value)[:500]},
                }
            )
        # Persist stable ids into checkpoint state so the next resume does not
        # renumber from 1 and collide with already-stored job_events rows.
        state["events"] = list(events)
        return RunOutcome(
            run_id=run_id,
            interrupted=payload_value is not None,
            interrupt_payload=payload_value if isinstance(payload_value, dict) else None,
            approval_status=str(state.get("approval_status") or "failed"),
            stop_reason=state.get("stop_reason"),
            events=events,
            state=state,
            elapsed_ms=self._elapsed_ms[run_id],
        )

    def _config(self, run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}, "recursion_limit": 80}


def _interrupt_values(snapshot: Any) -> list[Any]:
    values: list[Any] = []
    for item in getattr(snapshot, "interrupts", ()) or ():
        values.append(getattr(item, "value", item))
    return values


def _coerce_interrupt(raw: Any) -> list[Any]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [getattr(item, "value", item) for item in raw]
    return [getattr(raw, "value", raw)]
