"""Search and fetch ports.

The default adapters mirror V1: Tavily for search and `tools.validate_public_url`
plus `tools.scrape_url` for bounded public HTML. PDF bytes are never parsed.
`scrape_url` pins the validated IPs for urllib3's `socket.getaddrinfo` during
that one request. That is not an egress proxy and does not close SSRF.
"""
from __future__ import annotations

import hashlib
import re
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.app.observability import start_span
from backend.app.schemas.research import FetchResult, SearchHit


class RetrievalError(RuntimeError):
    pass


class RetrievalPort(Protocol):
    def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        ...

    def fetch(self, url: str) -> FetchResult:
        ...


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    scheme = (parsed.scheme or "https").lower()
    return urlunparse((scheme, host, path, "", query, ""))


def domain_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def clean_query(text: str, limit: int = 200) -> str:
    collapsed = " ".join(re.sub(r"[\x00-\x1f]", " ", text).split())
    return collapsed[:limit]


def search_public_web(query: str, *, max_results: int, client: object | None = None) -> list[SearchHit]:
    """Structured search using the same Tavily client pattern as V1 `web_search`."""
    with start_span("search.call", max_results=max_results) as span:
        hits = _search_public_web(query, max_results=max_results, client=client)
        span.set(hit_count=len(hits))
        return hits


def _search_public_web(query: str, *, max_results: int, client: object | None = None) -> list[SearchHit]:
    search_client = client
    if search_client is None:
        import os

        key = os.environ.get("TAVILY_API_KEY")
        if not key:
            raise RetrievalError("missing_search_key")
        from tavily import TavilyClient

        search_client = TavilyClient(api_key=key)
    bounded = max(1, min(max_results, 5))
    raw = search_client.search(query=query, max_results=bounded)  # type: ignore[attr-defined]
    rows = raw.get("results") if isinstance(raw, dict) else getattr(raw, "results", None)
    hits: list[SearchHit] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        hits.append(
            SearchHit(
                title=str(row.get("title") or url)[:300],
                url=url,
                snippet=str(row.get("content") or "")[:500],
            )
        )
    return hits


def fetch_public_html(
    url: str,
    *,
    validate_public_url=None,
    scrape=None,
) -> FetchResult:
    """Validate then scrape one public HTML URL. Blocked URLs are not fetched."""
    with start_span("source.fetch", domain=domain_of(url)) as span:
        result = _fetch_public_html(url, validate_public_url=validate_public_url, scrape=scrape)
        span.set(extraction_method=result.extraction_method, fetched=result.extraction_method == "html")
        return result


def _fetch_public_html(
    url: str,
    *,
    validate_public_url=None,
    scrape=None,
) -> FetchResult:
    if validate_public_url is None or scrape is None:
        from tools import scrape_url
        from tools import validate_public_url as v1_validate

        validate_public_url = validate_public_url or v1_validate
        if scrape is None:
            def scrape(target: str) -> str:
                return str(scrape_url.invoke({"url": target}))

    try:
        validate_public_url(url)
    except Exception:
        return FetchResult(
            url=url,
            text="",
            extraction_method="failed",
            caveat="URL blocked by the public-web policy.",
        )
    try:
        raw = scrape(url)
    except Exception:
        return FetchResult(
            url=url,
            text="",
            extraction_method="failed",
            caveat="Could not extract this source.",
        )
    return classify_scrape(url, str(raw))


def classify_scrape(url: str, raw: str) -> FetchResult:
    text = raw.strip()
    if text.startswith("This source is not an HTML") or text.startswith("This page exceeds"):
        return FetchResult(url=url, text="", extraction_method="snippet", caveat=text[:300])
    if text.startswith("Too many redirects") or text.startswith("Could not extract"):
        return FetchResult(url=url, text="", extraction_method="failed", caveat=text[:300])
    if text.startswith("Source:"):
        _, _, remainder = text.partition("\n")
        text = remainder.strip() or text
    return FetchResult(url=url, text=text[:6000], extraction_method="html")


class V1Retrieval:
    """Live adapter. Tests inject a fake port instead of constructing this."""

    def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        return search_public_web(query, max_results=max_results)

    def fetch(self, url: str) -> FetchResult:
        return fetch_public_html(url)
