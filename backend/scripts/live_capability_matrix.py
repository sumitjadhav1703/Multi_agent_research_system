"""Live provider capability matrix for ResearchMind role aliases.

Probes each configured role for:
  - text: short completion returns non-empty content
  - json: model returns parseable JSON object in content
  - tools: optional tool-call round-trip when tools= is accepted

Prints pass/fail, role, alias, model id, capability, and error_class only.
Never prints secrets, prompts, response bodies, or exception text.
"""
from __future__ import annotations

import json
import logging
import os
import sys

os.environ.setdefault("LITELLM_LOG", "ERROR")
logging.disable(logging.CRITICAL)

_PING_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "record_ping",
            "description": "Record that the model received the ping.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean", "description": "Always true."},
                },
                "required": ["ok"],
            },
        },
    }
]


def _error_class(exc: BaseException) -> str:
    return getattr(exc, "error_class", None) or type(exc).__name__


def _tool_call_present(raw: object) -> bool:
    message = getattr(raw, "choices", None)
    if message:
        try:
            msg = message[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                return True
        except (IndexError, AttributeError):
            pass
    if isinstance(raw, dict):
        choices = raw.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            if msg.get("tool_calls"):
                return True
    return False


def _run_capability(
    client: object,
    role: str,
    capability: str,
) -> tuple[str, str]:
    """Return (status, error_class)."""
    try:
        if capability == "text":
            response = client.complete(
                role,
                [
                    {"role": "system", "content": "Reply with the single word OK."},
                    {"role": "user", "content": "ping"},
                ],
                max_tokens=128,
                temperature=0,
            )
            return ("pass" if response.content else "fail", "")

        if capability == "json":
            response = client.complete(
                role,
                [
                    {
                        "role": "system",
                        "content": (
                            "Reply with a JSON object only. "
                            'Exact shape: {"ok": true}. No markdown.'
                        ),
                    },
                    {"role": "user", "content": "emit"},
                ],
                max_tokens=128,
                temperature=0,
            )
            text = (response.content or "").strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:].strip()
            data = json.loads(text)
            if isinstance(data, dict) and data.get("ok") is True:
                return ("pass", "")
            return ("fail", "invalid_json_shape")

        if capability == "tools":
            response = client.complete(
                role,
                [
                    {
                        "role": "system",
                        "content": "Call record_ping with ok=true. Do not answer in prose.",
                    },
                    {"role": "user", "content": "ping"},
                ],
                tools=_PING_TOOL,
                max_tokens=128,
                temperature=0,
            )
            if _tool_call_present(response.raw):
                return ("pass", "")
            # Some free models answer in text instead of tool_calls.
            if response.content and "record_ping" in response.content:
                return ("pass", "text_tool_mention")
            return ("fail", "no_tool_call")

        return ("fail", "unknown_capability")
    except Exception as exc:  # noqa: BLE001 — report class only
        return ("fail", _error_class(exc))


def main() -> int:
    from backend.app.core.config import Settings
    from backend.app.providers.client import ModelClient
    from backend.app.providers.router_factory import (
        ROLE_ALIASES,
        _api_key_for_model,
        create_router,
    )

    settings = Settings()
    print("matrix live_capability_matrix")
    print(f"use_mock_provider_flag {str(settings.use_mock_provider).lower()}")
    print(f"key_present groq {str(bool(settings.groq_api_key)).lower()}")
    print(
        "key_present gemini "
        f"{str(bool(settings.gemini_api_key or settings.google_api_key)).lower()}"
    )
    print(f"key_present mistral {str(bool(settings.mistral_api_key)).lower()}")
    print(f"key_present openrouter {str(bool(settings.openrouter_api_key)).lower()}")
    print("live_mode forced")

    router = create_router(settings, force_mock=False)
    client = ModelClient(settings, router=router)
    failures = 0
    capabilities = ("text", "json", "tools")

    for role, alias in ROLE_ALIASES.items():
        primary, _fallback = settings.role_models()[role]
        if primary.startswith("gemini/") and "2.0-flash" in primary and "latest" not in primary:
            print(
                f"warn role={role} model={primary} "
                "retired_id_risk=gemini-2.0-flash_use_flash-latest"
            )
        if not _api_key_for_model(settings, primary):
            failures += 1
            for capability in capabilities:
                print(
                    f"result role={role} alias={alias} model={primary} "
                    f"capability={capability} status=fail error_class=missing_key"
                )
            continue

        for capability in capabilities:
            status, error_class = _run_capability(client, role, capability)
            if status != "pass":
                failures += 1
            print(
                f"result role={role} alias={alias} model={primary} "
                f"capability={capability} status={status} error_class={error_class}"
            )

    print(f"failures {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
