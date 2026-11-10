"""Search and bounded, public-web extraction tools."""
import http.client
import os
import sys
from pathlib import Path

# V1 lives in v1/ but shares the SSRF helper from the repo-root backend package.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.tools import tool
from tavily import TavilyClient

from backend.app.security.egress_fetch import (
    EgressRedirectLimit,
    EgressTooLarge,
    fetch_public_url,
    resolve_global_ips,
)

load_dotenv()

# Bound for one HTML body. Tests may patch this; production stays at 1 MB.
_MAX_BODY_BYTES = 1_000_000


@tool
def web_search(query: str) -> str:
    """Search for reliable information. Return source titles, URLs and snippets."""
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    results = client.search(query=query, max_results=5)
    if not results.get("results"):
        raise ValueError("Search returned no sources.")
    return "\n----\n".join(
        f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['content'][:500]}"
        for r in results["results"]
    )


def validate_public_url(url):
    """Reject non-public URLs. Return the global IPs from this one lookup.

    Callers must dial these IP strings. A later lookup of the same name can
    rebind to a private address. This function does not connect, and it is
    not an egress proxy.
    """
    return resolve_global_ips(url)


@tool
def scrape_url(url: str) -> str:
    """Extract a bounded text excerpt from one public web page."""
    try:
        # Resolve once per hop and dial that IP with the original Host/SNI.
        # This does not close SSRF. A separate egress proxy is still required
        # before treating fetch as safe from a private network.
        fetched = fetch_public_url(url, max_bytes=_MAX_BODY_BYTES, require_html=True)
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
