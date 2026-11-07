"""Drop secrets and private text before they reach logs or span attributes."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Operational attributes are short tokens. Prose, URLs, and credential shapes are not.
_SECRET = re.compile(
    r"bearer\s+\S+"
    r"|\b(?:sk|rk)-[A-Za-z0-9_\-]{8,}\b"
    r"|\bgsk_[A-Za-z0-9]{8,}\b"
    r"|AIza[0-9A-Za-z\-_]{10,}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{8,}"
    r"|\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://\S+"
    r"|(?:api[_-]?key|password)\s*[:=]\s*\S+"
    r"|secret"
    r"|://",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"^[A-Za-z0-9_.:/@+\-]{1,120}$")
_SENSITIVE_KEYS = {
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "apikey",
    "xapikey",
    "secret",
    "password",
    "passwd",
    "accesstoken",
    "refreshtoken",
    "bearertoken",
    "bearer",
    "databaseurl",
    "connectionstring",
    "dsn",
    "groqapikey",
    "geminiapikey",
    "googleapikey",
    "mistralapikey",
    "openrouterapikey",
    "tavilyapikey",
    "turnstilesecretkey",
    "turnstilesecret",
    "prompt",
    "prompts",
    "messages",
    "message",
    "content",
    "sourcetext",
    "excerpt",
    "snippet",
    "topic",
    "report",
    "reportmarkdown",
    "markdown",
    "raw",
    "body",
    "html",
    "text",
    "pagetext",
    "query",
    "searchquery",
    "question",
    "comments",
    "reviewfeedback",
    "headers",
    "otelheaders",
}
_UNKNOWN_IF_NONE = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "retry_count",
    "fallback_used",
    "model",
}

AttributeValue = bool | int | float | str


def redact_text(value: str) -> str:
    """Replace credential-shaped or prose values. Short operational tokens stay."""
    if _SECRET.search(value) or any(char.isspace() for char in value) or len(value) > 180:
        return f"[redacted len={len(value)}]"
    return value


def safe_token(value: object, *, default: str = "unknown") -> str:
    """Keep a single operational token. Anything else becomes a fixed label."""
    if not isinstance(value, str) or not value:
        return default
    if not _TOKEN.fullmatch(value) or redact_text(value) != value:
        return "[redacted]"
    return value


def sanitize_attributes(raw: Mapping[str, Any] | None) -> dict[str, AttributeValue]:
    """Return a JSON- and OpenTelemetry-safe attribute map."""
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, AttributeValue] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        safe_key = safe_token(key, default="")
        if not safe_key or safe_key == "[redacted]":
            continue
        safe_value = _safe_value(key, value)
        if safe_value is None:
            continue
        cleaned[safe_key] = safe_value
    return cleaned


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _is_sensitive(key: str) -> bool:
    normal = _normalize_key(key)
    if normal in _SENSITIVE_KEYS:
        return True
    if normal.endswith("apikey") or normal.endswith("secret") or normal.endswith("password"):
        return True
    return "authorization" in normal or normal.endswith("cookie")


def _safe_value(key: str, value: Any) -> AttributeValue | None:
    if _is_sensitive(key):
        length = len(value) if isinstance(value, str) else None
        if length is None:
            return "[redacted]"
        return f"[redacted len={length}]"
    if value is None:
        if key in _UNKNOWN_IF_NONE or key.endswith("_tokens"):
            return "unknown"
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return "unknown"
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[redacted]"
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return f"[redacted count={len(value)}]"
    return "[redacted]"
