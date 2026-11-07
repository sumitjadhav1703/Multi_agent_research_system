"""Turnstile siteverify. Tests inject a verifier; the HTTP client is not used then."""
from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

import httpx

# The server secret is posted here. Overrides must stay on this Cloudflare endpoint.
OFFICIAL_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifier(Protocol):
    def verify(self, token: str, remote_ip: str | None) -> bool: ...


class StaticTurnstileVerifier:
    """Test double. Accepts only the tokens it was given."""

    def __init__(self, accepted: set[str]) -> None:
        self.accepted = set(accepted)

    def verify(self, token: str, remote_ip: str | None) -> bool:
        del remote_ip
        return bool(token) and token in self.accepted


class RejectingTurnstileVerifier:
    """Fail closed when no server-side secret is configured."""

    def verify(self, token: str, remote_ip: str | None) -> bool:
        del token, remote_ip
        return False


def canonical_turnstile_verify_url(url: str) -> str:
    """Accept only the Cloudflare siteverify URL, including an explicit port 443.

    Any other host would receive the Turnstile secret. Tests that need a fake
    host construct HttpTurnstileVerifier with allow_unpinned_url=True.
    """
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or host != "challenges.cloudflare.com"
        or path != "/turnstile/v0/siteverify"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "TURNSTILE_VERIFY_URL must be https://challenges.cloudflare.com/turnstile/v0/siteverify."
        )
    return OFFICIAL_TURNSTILE_VERIFY_URL


class HttpTurnstileVerifier:
    def __init__(
        self,
        secret: str,
        verify_url: str,
        *,
        client: httpx.Client | None = None,
        allow_unpinned_url: bool = False,
    ) -> None:
        self.secret = secret
        self.verify_url = verify_url if allow_unpinned_url else canonical_turnstile_verify_url(verify_url)
        self._client = client

    def verify(self, token: str, remote_ip: str | None) -> bool:
        if not token or not self.secret:
            return False
        payload = {"secret": self.secret, "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=5.0)
        try:
            response = client.post(self.verify_url, data=payload)
            if response.status_code != 200:
                return False
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        finally:
            if owns_client:
                client.close()
        return bool(isinstance(body, dict) and body.get("success") is True)


def build_turnstile_verifier(*, secret: str | None, verify_url: str) -> TurnstileVerifier:
    pinned = canonical_turnstile_verify_url(verify_url)
    if secret:
        return HttpTurnstileVerifier(secret, pinned)
    return RejectingTurnstileVerifier()
