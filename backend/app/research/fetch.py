"""Bounded public-HTML extraction for research workers.

`fetch_public_url` validates every hop (resolve once, dial that IP, Host/SNI keep the
hostname), so there is no separate pre-check lookup here. This is in-process only and
does not close SSRF. Results use short status sentences that `classify_scrape` maps.
"""
from __future__ import annotations

import http.client

from bs4 import BeautifulSoup

from backend.app.security.egress_fetch import EgressRedirectLimit, EgressTooLarge, fetch_public_url

MAX_BODY_BYTES = 1_000_000
FETCH_DEADLINE_SECONDS = 15.0


def scrape_url(url: str) -> str:
    """Extract a bounded text excerpt from one public web page."""
    try:
        fetched = fetch_public_url(
            url,
            max_bytes=MAX_BODY_BYTES,
            require_html=True,
            deadline_seconds=FETCH_DEADLINE_SECONDS,
        )
    except EgressTooLarge:
        return "This page exceeds the extraction limit. Use the search snippet instead."
    except EgressRedirectLimit:
        return "Too many redirects. Use the search snippet and disclose the limitation."
    except (ValueError, OSError, TimeoutError, UnicodeError, http.client.HTTPException):
        return "Could not extract this source. Use the search snippet and disclose the limitation."
    if "text/html" not in fetched.content_type.lower():
        return "This source is not an HTML page. Use the search snippet and disclose the limitation."
    soup = BeautifulSoup(fetched.body, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return f"Source: {fetched.url}\n{soup.get_text(separator=' ', strip=True)[:6000]}"
