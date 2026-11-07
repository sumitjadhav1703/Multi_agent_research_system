"""Runtime telemetry. DeepEval scores are a separate path and are not emitted here."""
from backend.app.observability.logging import configure_logging, emit
from backend.app.observability.redaction import redact_text, safe_token, sanitize_attributes
from backend.app.observability.tracing import (
    configure_tracing,
    export_mode,
    shutdown_tracing,
    start_span,
    traced_graph_node,
)

__all__ = [
    "configure_logging",
    "configure_observability",
    "configure_tracing",
    "emit",
    "export_mode",
    "redact_text",
    "safe_token",
    "sanitize_attributes",
    "shutdown_observability",
    "shutdown_tracing",
    "start_span",
    "traced_graph_node",
]


def configure_observability() -> str:
    """Attach the JSON log handler and, when configured, an OTLP or console exporter.

    The default is a no-op trace export so a demo boots without a collector.
    """
    configure_logging()
    return configure_tracing()


def shutdown_observability() -> None:
    shutdown_tracing()
