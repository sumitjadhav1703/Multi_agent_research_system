"""Safe service errors. Messages must not include URLs, tokens, or driver text."""
from __future__ import annotations


class JobServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
