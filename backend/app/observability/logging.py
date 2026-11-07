"""One JSON object per telemetry event. The handler does not print tracebacks."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from backend.app.observability.redaction import redact_text, sanitize_attributes

_CONFIGURED = False
_LOGGER_NAME = "researchmind.telemetry"


class JsonFormatter(logging.Formatter):
    """Format a log record as one redacted JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "event": redact_text(record.getMessage()),
        }
        fields = getattr(record, "telemetry", None)
        if isinstance(fields, dict):
            payload["fields"] = sanitize_attributes(fields)
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_class"] = record.exc_info[0].__name__
        return json.dumps(payload, default=_json_default, separators=(",", ":"))


def _json_default(_value: object) -> str:
    return "[redacted]"


def configure_logging() -> None:
    """Attach a JSON handler to the telemetry logger. Other loggers are left alone."""
    global _CONFIGURED
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(_level_from_env())
    logger.propagate = False
    if _CONFIGURED:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    _CONFIGURED = True


def emit(event: str, fields: dict[str, Any] | None = None, *, level: int = logging.INFO) -> None:
    configure_logging()
    logger = logging.getLogger(_LOGGER_NAME)
    logger.log(level, event, extra={"telemetry": sanitize_attributes(fields or {})})


def _level_from_env() -> int:
    name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    value = getattr(logging, name, None)
    if isinstance(value, int):
        return value
    return logging.INFO
