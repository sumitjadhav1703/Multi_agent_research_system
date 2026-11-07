"""ASGI request span. This does not buffer the body, so SSE can still stream."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from backend.app.observability.tracing import start_span

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class RequestSpanMiddleware:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method") if isinstance(scope.get("method"), str) else ""
        path = scope.get("path") if isinstance(scope.get("path"), str) else ""
        status_code = {"value": 0}

        async def send_wrapper(message: Message) -> None:
            if message.get("type") == "http.response.start":
                code = message.get("status")
                if isinstance(code, int):
                    status_code["value"] = code
            await send(message)

        with start_span("http.request", http_method=method, http_target=path) as recorder:
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                if status_code["value"]:
                    recorder.set(http_status=status_code["value"])
