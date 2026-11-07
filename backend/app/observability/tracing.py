"""OpenTelemetry spans for the research path.

Export is off unless OTEL_TRACES_EXPORTER or OTEL_EXPORTER_OTLP_ENDPOINT says
otherwise. Attributes are redacted before they are stored. A provider call that
dies before its node finishes can run again, so the same logical call can emit
more than one span.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import wraps
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from backend.app.observability.logging import emit
from backend.app.observability.redaction import safe_token, sanitize_attributes

_PROVIDER: Any = None
_ATTACHED: set[str] = set()
_FLUSHABLE: list[Any] = []

_NODE_SPANS = {
    "plan": "planner.invoke",
    "worker": "researcher.worker",
    "extract_claims": "evidence.extract",
    "verify": "claim.verify",
    "write": "report.write",
    "human_review": "human.review",
}


class SpanRecorder:
    """Collect redacted attributes onto the active span."""

    def __init__(self, span: Any) -> None:
        self.span = span
        self.fields: dict[str, Any] = {}
        self.passthrough = False

    def set(self, **attributes: Any) -> None:
        safe = sanitize_attributes(attributes)
        self.fields.update(safe)
        if self.span is None:
            return
        for key, value in safe.items():
            try:
                self.span.set_attribute(key, value)
            except Exception:
                continue


def export_mode() -> str:
    """Return noop, console, or otlp from process environment names only."""
    if _flag("OTEL_SDK_DISABLED"):
        return "noop"
    choice = os.environ.get("OTEL_TRACES_EXPORTER", "").strip().lower()
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if choice in {"none", "noop"}:
        return "noop"
    if choice == "console":
        return "console"
    if choice == "otlp":
        return "otlp" if endpoint else "noop"
    if choice == "" and endpoint:
        return "otlp"
    return "noop"


def configure_tracing() -> str:
    """Install a console or OTLP exporter when requested. Default is no export."""
    mode = export_mode()
    if mode == "noop" or mode in _ATTACHED:
        return "noop" if mode == "noop" else mode
    provider = _ensure_provider()
    if provider is None:
        return "noop"
    try:
        if mode == "console":
            _attach_console(provider)
        else:
            _attach_otlp(provider)
    except Exception as exc:
        emit(
            "otel.exporter_unavailable",
            {"exporter": mode, "error.class": type(exc).__name__},
            level=logging.ERROR,
        )
        return "noop"
    _ATTACHED.add(mode)
    return mode


def shutdown_tracing() -> None:
    """Flush exporters. The provider stays usable so a later request can still record spans."""
    for processor in list(_FLUSHABLE):
        try:
            processor.force_flush(timeout_millis=2000)
        except Exception as exc:
            emit(
                "otel.flush_failed",
                {"error.class": type(exc).__name__},
                level=logging.ERROR,
            )


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[SpanRecorder]:
    span_name = safe_token(name, default="span")
    if span_name == "[redacted]":
        span_name = "span"
    tracer = trace.get_tracer("researchmind")
    started = time.perf_counter()
    with tracer.start_as_current_span(span_name) as span:
        recorder = SpanRecorder(span)
        recorder.set(**attributes)
        try:
            yield recorder
        except Exception as exc:
            if not recorder.passthrough:
                recorder.set(**{"error.class": type(exc).__name__, "status": "error"})
                try:
                    span.set_status(Status(StatusCode.ERROR))
                except Exception:
                    pass
            raise
        else:
            if "status" not in recorder.fields:
                recorder.set(status="ok")
        finally:
            recorder.set(duration_ms=int((time.perf_counter() - started) * 1000))
            emit(span_name, recorder.fields)


def traced_graph_node(node_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap one graph node. State text such as the topic is not copied onto the span."""
    span_name = _NODE_SPANS.get(node_name, "graph.node")

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        state = args[0] if args else kwargs.get("state")
        with start_span(span_name, node=node_name, **_state_fields(state)) as span:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                # LangGraph uses GraphInterrupt to pause for human review.
                if type(exc).__name__ == "GraphInterrupt":
                    span.passthrough = True
                    span.set(status="paused", interrupt="GraphInterrupt")
                raise

    return wrapper


def begin_db_span(operation: str, system: str) -> tuple[Any, float]:
    tracer = trace.get_tracer("researchmind")
    span = tracer.start_span("db.op")
    fields = sanitize_attributes({"db.operation": operation, "db.system": system})
    for key, value in fields.items():
        try:
            span.set_attribute(key, value)
        except Exception:
            continue
    return span, time.perf_counter()


def end_db_span(span: Any, started: float, *, error_class: str | None = None) -> None:
    fields: dict[str, Any] = {
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "status": "error" if error_class else "ok",
    }
    if error_class:
        fields["error.class"] = error_class
        try:
            span.set_status(Status(StatusCode.ERROR))
        except Exception:
            pass
    safe = sanitize_attributes(fields)
    for key, value in safe.items():
        try:
            span.set_attribute(key, value)
        except Exception:
            continue
    try:
        span.end()
    except Exception:
        return
    emit("db.op", {**_span_fields(span), **safe}, level=logging.DEBUG)


class RedactingSpanProcessor:
    """Scrub span attributes before a later processor exports them.

    This is a SpanProcessor duck type. `_on_ending` is required by the SDK's
    multi-processor, which calls it on every registered processor.
    """

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        del span, parent_context

    def _on_ending(self, span: Any) -> None:
        del span

    def on_end(self, span: Any) -> None:
        _scrub_span(span)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


def _ensure_provider() -> Any:
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
    except Exception as exc:
        emit(
            "otel.provider_unavailable",
            {"error.class": type(exc).__name__},
            level=logging.ERROR,
        )
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": _service_name()}))
    provider.add_span_processor(RedactingSpanProcessor())
    trace.set_tracer_provider(provider)
    _PROVIDER = provider
    return provider


def _attach_console(provider: Any) -> None:
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    _FLUSHABLE.append(processor)


def _attach_otlp(provider: Any) -> None:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # The exporter reads OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS.
    # Those values are never written to our logs.
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)
    _FLUSHABLE.append(processor)


def _service_name() -> str:
    return safe_token(os.environ.get("OTEL_SERVICE_NAME", "researchmind"), default="researchmind")


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _state_fields(state: object) -> dict[str, str]:
    if not isinstance(state, Mapping):
        return {}
    fields: dict[str, str] = {}
    run_id = safe_token(state.get("run_id"), default="")
    if run_id and run_id != "[redacted]":
        fields["run_id"] = run_id
    task = state.get("task")
    if isinstance(task, Mapping):
        subquestion_id = safe_token(task.get("subquestion_id"), default="")
        if subquestion_id and subquestion_id != "[redacted]":
            fields["subquestion_id"] = subquestion_id
    return fields


def _span_fields(span: Any) -> dict[str, Any]:
    attributes = getattr(span, "attributes", None)
    if isinstance(attributes, Mapping):
        return sanitize_attributes(dict(attributes))
    return {}


def _scrub_span(span: Any) -> None:
    attributes = getattr(span, "_attributes", None)
    if attributes is not None:
        try:
            current = dict(attributes)
        except Exception:
            current = None
        if isinstance(current, dict):
            cleaned = sanitize_attributes(current)
            if cleaned != current:
                was_immutable = bool(getattr(attributes, "_immutable", False))
                try:
                    if was_immutable:
                        attributes._immutable = False
                    attributes.clear()
                    attributes.update(cleaned)
                except Exception:
                    pass
                finally:
                    if was_immutable:
                        try:
                            attributes._immutable = True
                        except Exception:
                            pass
    status = getattr(span, "_status", None)
    description = getattr(status, "description", None)
    if description:
        try:
            span._status = Status(status.status_code)
        except Exception:
            pass
    events = getattr(span, "_events", None)
    if events is not None:
        try:
            events.clear()
        except Exception:
            try:
                span._events = ()
            except Exception:
                pass
