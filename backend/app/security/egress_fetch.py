"""One public-web fetch path: resolve once, dial that IP, re-check redirects.

This is in-process only. It is not a separate egress proxy. Any code that
opens its own socket bypasses it. Do not describe SSRF as closed.
"""
from __future__ import annotations

import ipaddress
import socket
import ssl
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import http.client

_MAX_URL_LENGTH = 8192
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "metadata.google.com",
        "metadata.internal",
        "instance-data",
        "instance-data.ec2.internal",
    }
)
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain")
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_V4_COMPAT = ipaddress.IPv6Network("::/96")

Resolver = Callable[..., list]
Dial = Callable[[str, int, float], socket.socket]
TlsWrap = Callable[[socket.socket, str], socket.socket]


class EgressBlocked(ValueError):
    """The URL failed the public-web policy."""


class EgressTooLarge(Exception):
    """The response body exceeded the byte cap."""


class EgressRedirectLimit(Exception):
    """The redirect chain exceeded the hop cap."""


@dataclass(frozen=True)
class PublicTarget:
    url: str
    scheme: str
    host: str
    port: int
    target: str


@dataclass(frozen=True)
class PublicFetch:
    url: str
    status: int
    content_type: str
    body: bytes


def resolve_global_ips(url: str, *, resolver: Resolver | None = None) -> list[str]:
    """Return the global IPs from one lookup. Do not connect.

    A later lookup of the same name can rebind. Callers that dial must use
    these strings as IP literals, not the hostname.
    """
    parsed = _parse_public_url(url)
    literal = _literal_ip(parsed.host)
    if literal is not None:
        if _blocked_ip(literal):
            raise EgressBlocked("Private network addresses are blocked.")
        return [str(literal)]
    lookup = resolver or socket.getaddrinfo
    try:
        records = lookup(parsed.host, parsed.port, type=socket.SOCK_STREAM)
    except UnicodeError:
        raise
    if not records:
        raise EgressBlocked("Private network addresses are blocked.")
    ips: list[str] = []
    for record in records:
        try:
            ip = ipaddress.ip_address(record[4][0])
        except (ValueError, IndexError) as exc:
            raise EgressBlocked("Private network addresses are blocked.") from exc
        if _blocked_ip(ip):
            raise EgressBlocked("Private network addresses are blocked.")
        text = str(ip)
        if text not in ips:
            ips.append(text)
    if not ips:
        raise EgressBlocked("Private network addresses are blocked.")
    return ips


def fetch_public_url(
    url: str,
    *,
    resolver: Resolver | None = None,
    dial: Dial | None = None,
    tls_wrap: TlsWrap | None = None,
    max_bytes: int = 1_000_000,
    max_hops: int = 4,
    connect_timeout: float = 4.0,
    read_timeout: float = 8.0,
    deadline_seconds: float | None = None,
    require_html: bool = False,
) -> PublicFetch:
    """GET one public URL. Each hop is resolved once and dialed by that IP.

    The Host header and TLS SNI use the original hostname. Certificate
    verification stays on. Redirects are manual. A private, loopback,
    link-local, or metadata hop is rejected before its dial.
    """
    if max_bytes < 1 or max_hops < 1:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    current = url
    deadline = time.monotonic() + (
        deadline_seconds if deadline_seconds is not None else max_hops * (connect_timeout + read_timeout)
    )
    connector = dial or _dial_ip
    wrap = tls_wrap or _tls_wrap
    for _ in range(max_hops):
        if time.monotonic() >= deadline:
            raise TimeoutError("public fetch deadline exceeded")
        remaining = max(0.1, deadline - time.monotonic())
        parsed = _parse_public_url(current)
        ips = resolve_global_ips(current, resolver=resolver)
        sock = _connect_first(ips, parsed.port, min(connect_timeout, remaining), connector)
        try:
            sock.settimeout(min(connect_timeout, read_timeout, remaining))
            if parsed.scheme == "https":
                sock = wrap(sock, parsed.host)
            conn, response = _http_get(sock, parsed, read_timeout)
            try:
                fetched, redirect_to = _interpret(
                    response,
                    current,
                    max_bytes=max_bytes,
                    require_html=require_html,
                )
            finally:
                response.close()
                conn.close()
        finally:
            sock.close()
        if redirect_to is None:
            if fetched is None:
                raise EgressBlocked("Only public HTTP(S) URLs are supported.")
            return fetched
        current = redirect_to
    raise EgressRedirectLimit("Too many redirects.")


def _connect_first(ips: list[str], port: int, timeout: float, dial: Dial) -> socket.socket:
    last: OSError | None = None
    for ip in ips:
        try:
            return dial(ip, port, timeout)
        except OSError as exc:
            last = exc
    if last is None:
        raise EgressBlocked("Private network addresses are blocked.")
    raise last


def _dial_ip(ip: str, port: int, timeout: float) -> socket.socket:
    """Connect to an already-checked IP literal. Do not resolve a hostname."""
    address = ipaddress.ip_address(ip)
    if _blocked_ip(address):
        raise EgressBlocked("Private network addresses are blocked.")
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        if address.version == 6:
            sock.connect((str(address), port, 0, 0))
        else:
            sock.connect((str(address), port))
        return sock
    except Exception:
        sock.close()
        raise


def _tls_wrap(sock: socket.socket, hostname: str) -> socket.socket:
    context = ssl.create_default_context()
    return context.wrap_socket(sock, server_hostname=hostname)


def _http_get(
    sock: socket.socket,
    parsed: PublicTarget,
    read_timeout: float,
) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    conn = http.client.HTTPConnection(parsed.host, parsed.port, timeout=read_timeout)
    conn.auto_open = False
    conn.sock = sock
    sock.settimeout(read_timeout)
    conn.putrequest("GET", parsed.target, skip_host=True, skip_accept_encoding=True)
    conn.putheader("Host", _host_header(parsed.host, parsed.port, parsed.scheme))
    conn.putheader("User-Agent", "ResearchMind/1.0")
    conn.putheader("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
    conn.putheader("Accept-Encoding", "identity")
    conn.putheader("Connection", "close")
    conn.endheaders()
    return conn, conn.getresponse()


def _interpret(
    response: http.client.HTTPResponse,
    current: str,
    *,
    max_bytes: int,
    require_html: bool,
) -> tuple[PublicFetch | None, str | None]:
    status = response.status
    if status in _REDIRECT_STATUSES:
        locations = response.headers.get_all("Location") or []
        if len(locations) != 1:
            raise EgressBlocked("Only public HTTP(S) URLs are supported.")
        location = locations[0].strip()
        if not location or len(location) > _MAX_URL_LENGTH:
            raise EgressBlocked("Only public HTTP(S) URLs are supported.")
        if any(ord(char) < 32 or ord(char) == 127 for char in location):
            raise EgressBlocked("Only public HTTP(S) URLs are supported.")
        return None, urljoin(current, location)
    if status < 200 or status >= 300:
        raise OSError(f"http status {status}")
    _reject_smuggling(response)
    content_type = response.getheader("Content-Type") or ""
    if any(char in content_type for char in "\r\n\x00"):
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    if require_html and "text/html" not in content_type.lower():
        return PublicFetch(url=current, status=status, content_type=content_type, body=b""), None
    declared = _content_length(response)
    if declared is not None and declared > max_bytes:
        raise EgressTooLarge("response exceeds the extraction limit")
    body = _read_capped(response, max_bytes)
    body = _decode_content(body, response.getheader("Content-Encoding") or "", max_bytes)
    return PublicFetch(url=current, status=status, content_type=content_type, body=body), None


def _reject_smuggling(response: http.client.HTTPResponse) -> None:
    lengths = response.headers.get_all("Content-Length") or []
    encodings = response.headers.get_all("Transfer-Encoding") or []
    if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")


def _content_length(response: http.client.HTTPResponse) -> int | None:
    raw = response.getheader("Content-Length")
    if raw is None:
        return None
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.") from exc
    if value < 0:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    return value


def _read_capped(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    remaining = max_bytes + 1
    chunks: list[bytes] = []
    while remaining > 0:
        chunk = response.read(min(16384, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    if len(body) > max_bytes:
        raise EgressTooLarge("response exceeds the extraction limit")
    return body


def _decode_content(body: bytes, encoding: str, max_bytes: int) -> bytes:
    enc = encoding.split(",")[0].strip().lower()
    if enc in ("", "identity"):
        return body
    if enc == "gzip":
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif enc == "deflate":
        try:
            return _decompress(body, max_bytes, zlib.MAX_WBITS)
        except OSError:
            return _decompress(body, max_bytes, -zlib.MAX_WBITS)
    else:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    return _decompress(body, max_bytes, decompressor=decompressor)


def _decompress(
    body: bytes,
    max_bytes: int,
    window: int | None = None,
    *,
    decompressor: zlib.Decompress | None = None,
) -> bytes:
    if decompressor is None:
        if window is None:
            raise OSError("content encoding failed")
        decompressor = zlib.decompressobj(window)
    try:
        out = decompressor.decompress(body, max_bytes + 1)
    except zlib.error as exc:
        raise OSError("content encoding failed") from exc
    if len(out) > max_bytes or decompressor.unconsumed_tail:
        raise EgressTooLarge("response exceeds the extraction limit")
    return out


def _host_header(host: str, port: int, scheme: str) -> str:
    formatted = f"[{host}]" if ":" in host else host
    default = 443 if scheme == "https" else 80
    if port == default:
        return formatted
    return f"{formatted}:{port}"


def _parse_public_url(url: str) -> PublicTarget:
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_LENGTH:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    try:
        parsed = urlparse(url)
        explicit_port = parsed.port
    except ValueError as exc:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.") from exc
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or explicit_port not in (None, 80, 443)
    ):
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    host = _normalize_host(parsed.hostname)
    if _blocked_hostname(host):
        raise EgressBlocked("Private network addresses are blocked.")
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if not path.startswith("/") or any(char in path or char in parsed.query for char in ("\r", "\n", "\x00", " ")):
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    target = path if not parsed.query else f"{path}?{parsed.query}"
    return PublicTarget(url=url, scheme=parsed.scheme, host=host, port=port, target=target)


def _normalize_host(hostname: str) -> str:
    host = hostname.strip().lower()
    if host.endswith("."):
        host = host[:-1]
    if not host or "%" in host or "\\" in host or "/" in host:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise EgressBlocked("Only public HTTP(S) URLs are supported.") from exc


def _blocked_hostname(host: str) -> bool:
    if host in _BLOCKED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _BLOCKED_SUFFIXES)


def _looks_like_ipv4_literal(host: str) -> bool:
    lowered = host.lower()
    if lowered.startswith("0x") and all(char in "0123456789abcdefx" for char in lowered):
        return True
    if host.isdigit():
        return True
    parts = host.split(".")
    return len(parts) > 1 and all(part.isdigit() for part in parts)


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if not _looks_like_ipv4_literal(host):
        return None
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError as exc:
        raise EgressBlocked("Private network addresses are blocked.") from exc


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reject addresses that must not be dialed.

    ``is_global`` alone is not enough: multicast is global in Python 3.13,
    and NAT64 / IPv4-compatible addresses can embed a private IPv4 address
    while still reporting ``is_global``.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None and _blocked_ip(embedded):
            return True
    if (
        ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or not ip.is_global
    ):
        return True
    return False


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    mapped = ip.ipv4_mapped
    if mapped is not None:
        return mapped
    if ip in _NAT64 or ip in _V4_COMPAT:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None
