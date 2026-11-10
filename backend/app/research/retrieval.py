"""Search and fetch adapters.

Tavily for search and `research.fetch.scrape_url` for bounded public HTML. PDF
bytes are never parsed. The fetch resolves each hop once and dials that global
IP, with the original hostname as Host and TLS SNI. This is in-process only. It
is not a separate egress proxy and does not close SSRF.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.app.core.config import get_settings
from backend.app.observability import start_span
from backend.app.schemas.research import FetchResult, SearchHit


class RetrievalError(RuntimeError):
    pass


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


_SEARCH_TIMEOUT_SECONDS = 15.0
_tavily_cache: tuple[str, object] | None = None


def _tavily_client() -> object:
    """One TavilyClient per process (per key); built lazily."""
    global _tavily_cache
    key = get_settings().tavily_api_key
    if not key:
        raise RetrievalError("missing_search_key")
    if _tavily_cache is None or _tavily_cache[0] != key:
        from tavily import TavilyClient

        _tavily_cache = (key, TavilyClient(api_key=key))
    return _tavily_cache[1]


def search_public_web(query: str, *, max_results: int, client: object | None = None) -> list[SearchHit]:
    """Structured search using the same Tavily client pattern as V1 `web_search`."""
    with start_span("search.call", max_results=max_results) as span:
        hits = _search_public_web(query, max_results=max_results, client=client)
        span.set(hit_count=len(hits))
        return hits


def _search_public_web(query: str, *, max_results: int, client: object | None = None) -> list[SearchHit]:
    search_client = client or _tavily_client()
    bounded = max(1, min(max_results, 5))
    kwargs = {} if client is not None else {"timeout": _SEARCH_TIMEOUT_SECONDS}
    raw = search_client.search(query=query, max_results=bounded, **kwargs)  # type: ignore[attr-defined]
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


def fetch_public_html(url: str, *, scrape=None) -> FetchResult:
    """Scrape one public HTML URL. Blocked URLs fail inside the fetch and are not dialed."""
    with start_span("source.fetch", domain=domain_of(url)) as span:
        result = _fetch_public_html(url, scrape=scrape)
        span.set(extraction_method=result.extraction_method, fetched=result.extraction_method == "html")
        return result


def _fetch_public_html(url: str, *, scrape=None) -> FetchResult:
    if scrape is None:
        from backend.app.research.fetch import scrape_url as scrape
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
