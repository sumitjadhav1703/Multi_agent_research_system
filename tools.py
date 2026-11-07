"""Search and bounded, public-web extraction tools."""
import ipaddress
import os
import socket
import threading
from contextlib import contextmanager
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.tools import tool
from tavily import TavilyClient

load_dotenv()

# Held only around one pinned requests.get. Two scrapes in this process wait,
# so one cannot restore socket.getaddrinfo while the other is still connecting.
_DNS_PIN_LOCK = threading.Lock()


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

    Callers must connect to these IPs. A later lookup of the same name can
    rebind to a private address. This function does not connect.
    """
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError("Only public HTTP(S) URLs are supported.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("Private network addresses are blocked.")
    ips = []
    for record in addresses:
        ip = ipaddress.ip_address(record[4][0])
        if not ip.is_global:
            raise ValueError("Private network addresses are blocked.")
        ips.append(str(ip))
    return ips


def _global_ips(value):
    if not isinstance(value, list):
        return []
    ips = []
    for item in value:
        if not isinstance(item, str):
            return []
        try:
            ip = ipaddress.ip_address(item)
        except ValueError:
            return []
        if not ip.is_global:
            raise ValueError("Private network addresses are blocked.")
        ips.append(str(ip))
    return ips


@contextmanager
def _pin_public_resolution(hostname, ips):
    """Serve the already-checked IPs to urllib3's socket.getaddrinfo.

    urllib3's create_connection calls socket.getaddrinfo on the hostname.
    Replacing that lookup for the duration of one requests.get makes the TCP
    connection use the IPs validate_public_url just accepted. This is not an
    egress proxy. Code that connects without socket.getaddrinfo is not pinned,
    and a resolver change inside urllib3 would skip this pin.
    """
    if not hostname or not ips:
        yield
        return
    with _DNS_PIN_LOCK:
        original = socket.getaddrinfo
        names = {hostname.lower().strip("[]")}

        def pinned(host, port, *args, **kwargs):
            normalized = host.decode("ascii", "ignore") if isinstance(host, bytes) else str(host)
            if normalized.lower().strip("[]") not in names:
                return original(host, port, *args, **kwargs)
            family = args[0] if args else kwargs.get("family", 0)
            records = []
            for ip in ips:
                address = ipaddress.ip_address(ip)
                if address.version == 6:
                    item = (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port, 0, 0))
                else:
                    item = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
                if family in (0, socket.AF_UNSPEC, item[0]):
                    records.append(item)
            return records

        socket.getaddrinfo = pinned
        try:
            yield
        finally:
            socket.getaddrinfo = original


@tool
def scrape_url(url: str) -> str:
    """Extract a bounded text excerpt from one public web page."""
    try:
        # Each hop is checked, then that same answer is pinned for urllib3.
        # This does not close SSRF. An egress proxy is still required before
        # treating fetch as safe from a private network.
        for _ in range(4):
            parsed = urlparse(url)
            pinned_ips = _global_ips(validate_public_url(url))
            with _pin_public_resolution(parsed.hostname or "", pinned_ips):
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
