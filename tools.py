"""Search and bounded, public-web extraction tools."""
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.tools import tool
from tavily import TavilyClient

load_dotenv()


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
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError("Only public HTTP(S) URLs are supported.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private network addresses are blocked.")


@tool
def scrape_url(url: str) -> str:
    """Extract a bounded text excerpt from one public web page."""
    try:
        # shortcut: DNS is checked before requests resolves again; use an egress proxy
        # with connection-time IP enforcement before deploying on a private network.
        for _ in range(4):
            validate_public_url(url)
            with requests.get(url, timeout=(4, 8), headers={"User-Agent": "ResearchMind/1.0"},
                              allow_redirects=False, stream=True) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers["Location"])
                    continue
                response.raise_for_status()
                if "text/html" not in response.headers.get("Content-Type", "").lower():
                    return "This source is not an HTML page. Use the search snippet and disclose the limitation."
                body = bytearray()
                for chunk in response.iter_content(16384):
                    body.extend(chunk)
                    if len(body) > 1_000_000:
                        return "This page exceeds the extraction limit. Use the search snippet instead."
                soup = BeautifulSoup(bytes(body), "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                return f"Source: {url}\n{soup.get_text(separator=' ', strip=True)[:6000]}"
        return "Too many redirects. Use the search snippet and disclose the limitation."
    except (requests.RequestException, ValueError, OSError, KeyError):
        return "Could not extract this source. Use the search snippet and disclose the limitation."
