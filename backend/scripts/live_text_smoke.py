"""Text-completion smoke for allowlisted free providers.

Prints pass/fail, role alias, model id and error class only.
Never prints secrets, request bodies or exception text.
"""
from __future__ import annotations

import logging
import os
import sys

os.environ.setdefault("LITELLM_LOG", "ERROR")
logging.disable(logging.CRITICAL)


def main() -> int:
    from backend.app.core.config import Settings
    from backend.app.providers.client import ModelClient
    from backend.app.providers.router_factory import (
        ROLE_ALIASES,
        _api_key_for_model,
        create_router,
    )

    settings = Settings()
    print(f"use_mock_provider_flag {str(settings.use_mock_provider).lower()}")
    print(f"key_present groq {str(bool(settings.groq_api_key)).lower()}")
    print(f"key_present nvidia_nim {str(bool(settings.nvidia_nim_api_key)).lower()}")
    print(f"key_present openrouter {str(bool(settings.openrouter_api_key)).lower()}")
    print(f"key_present tavily {str(bool(settings.tavily_api_key)).lower()}")
    print("live_mode forced")

    router = create_router(settings, force_mock=False)
    client = ModelClient(settings, router=router)
    failures = 0
    for role, alias in ROLE_ALIASES.items():
        primary, _fallback = settings.role_models()[role]
        if not _api_key_for_model(settings, primary):
            failures += 1
            print(
                f"result role={role} alias={alias} model={primary} "
                "status=fail error_class=missing_key"
            )
            continue
        try:
            response = client.complete(
                role,
                [
                    {"role": "system", "content": "Reply with the single word OK."},
                    {"role": "user", "content": "ping"},
                ],
                max_tokens=128,
                temperature=0,
            )
            status = "pass" if response.content else "fail"
            if status != "pass":
                failures += 1
            print(
                f"result role={role} alias={alias} model={primary} "
                f"status={status} error_class="
            )
        except Exception as exc:  # noqa: BLE001 — report class only
            failures += 1
            error_class = getattr(exc, "error_class", None) or type(exc).__name__
            print(
                f"result role={role} alias={alias} model={primary} "
                f"status=fail error_class={error_class}"
            )
    print(f"failures {failures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
