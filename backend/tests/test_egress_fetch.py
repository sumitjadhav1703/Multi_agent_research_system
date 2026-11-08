"""In-process public fetch: one DNS answer, dial that IP, re-check every hop."""
from __future__ import annotations

import ipaddress
import socket
import ssl
import threading
import time
import unittest
import zlib
from unittest.mock import patch

from backend.app.security.egress_fetch import (
    EgressRedirectLimit,
    EgressTooLarge,
    _dial_ip,
    _tls_wrap,
    fetch_public_url,
    resolve_global_ips,
)

PUBLIC = "93.184.216.34"
OTHER = "1.1.1.1"


def _record(ip: str, port: int = 80):
    address = ipaddress.ip_address(ip)
    if address.version == 6:
        return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))


def _http_response(status: int, headers: dict[str, str], body: bytes, *, version: str = "HTTP/1.1") -> bytes:
    lines = [f"{version} {status} OK"]
    lowered = {key.lower() for key in headers}
    for key, value in headers.items():
        lines.append(f"{key}: {value}")
    if "content-length" not in lowered and "transfer-encoding" not in lowered and version != "HTTP/1.0":
        lines.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def _pair(payload: bytes, sink: list[bytes] | None = None) -> socket.socket:
    client, server = socket.socketpair()

    def serve() -> None:
        try:
            server.settimeout(2)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = server.recv(4096)
                if not chunk:
                    break
                data += chunk
            if sink is not None:
                sink.append(data)
            server.sendall(payload)
        except OSError:
            pass
        finally:
            server.close()

    threading.Thread(target=serve, daemon=True).start()
    return client


def _resolver(*ips: str):
    def lookup(host, port, *args, **kwargs):
        del host, args, kwargs
        return [_record(ip, port) for ip in ips]

    return lookup


class EgressFetchTests(unittest.TestCase):
    def test_private_mixed_and_metadata_answers_are_rejected(self) -> None:
        blocked = (
            ("127.0.0.1",),
            ("::1",),
            ("169.254.169.254",),
            ("10.0.0.1",),
            ("100.64.0.1",),
            ("100.100.100.200",),
            (PUBLIC, "10.0.0.1"),
            ("224.0.0.1",),
            ("::ffff:169.254.169.254",),
            ("64:ff9b::a9fe:a9fe",),
            ("::7f00:1",),
        )
        for ips in blocked:
            with self.subTest(ips=ips), patch(
                "backend.app.security.egress_fetch.socket.getaddrinfo",
                return_value=[_record(ip) for ip in ips],
            ), self.assertRaises(ValueError):
                resolve_global_ips("https://example.com/a")

    def test_legacy_literals_and_metadata_names_do_not_use_dns(self) -> None:
        def boom(*args, **kwargs):
            raise AssertionError(f"dns used for {args!r}")

        urls = (
            "http://169.254.169.254/latest/meta-data/",
            "http://2130706433/",
            "http://0x7f000001/",
            "http://0177.0.0.1/",
            "http://127.1/",
            "http://08.8.8.8/",
            "http://[::1]/",
            "http://[fd00:ec2::254]/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data.ec2.internal/",
            "http://localhost/",
            "file:///etc/passwd",
            "http://user:pass@example.com/",
            "http://example.com:8080/",
        )
        with patch("backend.app.security.egress_fetch.socket.getaddrinfo", side_effect=boom):
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    resolve_global_ips(url)

    def test_dial_uses_the_ip_literal_and_does_not_resolve(self) -> None:
        connects: list[tuple] = []

        class FakeSocket:
            def __init__(self, family, sock_type, proto=0, fileno=None):
                del family, sock_type, proto, fileno

            def settimeout(self, timeout):
                del timeout

            def connect(self, address):
                connects.append(address)
                raise TimeoutError("stopped")

            def close(self):
                return None

        def gai(*args, **kwargs):
            raise AssertionError("getaddrinfo")

        with patch("backend.app.security.egress_fetch.socket.socket", FakeSocket), patch(
            "backend.app.security.egress_fetch.socket.getaddrinfo", side_effect=gai
        ), self.assertRaises(TimeoutError):
            _dial_ip(PUBLIC, 443, 1.0)
        self.assertEqual(connects, [(PUBLIC, 443)])
        with patch("backend.app.security.egress_fetch.socket.socket", FakeSocket), self.assertRaises(TimeoutError):
            _dial_ip("2001:4860:4860::8888", 80, 1.0)
        self.assertEqual(connects[-1], ("2001:4860:4860::8888", 80, 0, 0))

    def test_dial_refuses_private_ips_and_hostnames(self) -> None:
        def boom(*args, **kwargs):
            raise AssertionError("socket opened")

        with patch("backend.app.security.egress_fetch.socket.socket", side_effect=boom):
            for ip in ("127.0.0.1", "169.254.169.254", "10.1.2.3", "::1"):
                with self.subTest(ip=ip), self.assertRaises(ValueError):
                    _dial_ip(ip, 80, 0.1)
        with self.assertRaises(ValueError):
            _dial_ip("example.com", 80, 0.1)

    def test_dns_rebind_dials_the_first_global_ip_only(self) -> None:
        calls = {"n": 0}
        connects: list[tuple] = []

        def gai(host, port, *args, **kwargs):
            del host, args, kwargs
            calls["n"] += 1
            ip = PUBLIC if calls["n"] == 1 else "127.0.0.1"
            return [_record(ip, port)]

        class FakeSocket:
            def __init__(self, family, sock_type, proto=0, fileno=None):
                del family, sock_type, proto, fileno

            def settimeout(self, timeout):
                del timeout

            def connect(self, address):
                connects.append(address)
                raise TimeoutError("stopped")

            def close(self):
                return None

        original = socket.getaddrinfo
        with patch("backend.app.security.egress_fetch.socket.getaddrinfo", side_effect=gai), patch(
            "backend.app.security.egress_fetch.socket.socket", FakeSocket
        ), self.assertRaises(TimeoutError):
            fetch_public_url("http://example.com/page")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(connects, [(PUBLIC, 80)])
        self.assertIs(socket.getaddrinfo, original)

    def test_fetch_sets_original_host_and_ignores_a_later_private_answer(self) -> None:
        calls = {"n": 0}
        seen: list[bytes] = []
        dialed: list[str] = []

        def gai(host, port, *args, **kwargs):
            del host, args, kwargs
            calls["n"] += 1
            ip = PUBLIC if calls["n"] == 1 else "127.0.0.1"
            return [_record(ip, port)]

        def dial(ip, port, timeout):
            del port, timeout
            dialed.append(ip)
            body = b"<p>Pinned</p>"
            return _pair(
                _http_response(200, {"Content-Type": "text/html; charset=utf-8"}, body),
                seen,
            )

        original = socket.getaddrinfo
        fetched = fetch_public_url("https://example.com/page", resolver=gai, dial=dial, tls_wrap=lambda sock, host: sock)
        self.assertEqual(dialed, [PUBLIC])
        self.assertEqual(calls["n"], 1)
        self.assertEqual(fetched.body, b"<p>Pinned</p>")
        self.assertIn(b"Host: example.com\r\n", seen[0])
        self.assertNotIn(b"127.0.0.1", seen[0])
        self.assertNotIn(PUBLIC.encode(), seen[0])
        self.assertIs(socket.getaddrinfo, original)

    def test_redirect_to_private_or_metadata_is_not_dialed(self) -> None:
        cases = (
            "http://127.0.0.1/secret",
            "http://169.254.169.254/latest/meta-data/",
            "http://0177.0.0.1/",
            "http://metadata.google.internal/",
        )
        for location in cases:
            dialed: list[str] = []

            def gai(host, port, *args, **kwargs):
                del args, kwargs
                if host != "example.com":
                    raise AssertionError(host)
                return [_record(PUBLIC, port)]

            def dial(ip, port, timeout, location=location):
                del port, timeout
                dialed.append(ip)
                return _pair(_http_response(302, {"Location": location}, b"SECRET"))

            with self.subTest(location=location), self.assertRaises(ValueError):
                fetch_public_url("http://example.com/start", resolver=gai, dial=dial)
            self.assertEqual(dialed, [PUBLIC])

    def test_redirect_hop_resolves_again_and_blocks_a_private_answer(self) -> None:
        dialed: list[str] = []

        def gai(host, port, *args, **kwargs):
            del args, kwargs
            ip = PUBLIC if host == "example.com" else "10.0.0.8"
            return [_record(ip, port)]

        def dial(ip, port, timeout):
            del port, timeout
            dialed.append(ip)
            return _pair(_http_response(302, {"Location": "http://cdn.example/secret"}, b""))

        with self.assertRaises(ValueError):
            fetch_public_url("http://example.com/", resolver=gai, dial=dial)
        self.assertEqual(dialed, [PUBLIC])

    def test_public_redirect_dials_the_second_validated_ip(self) -> None:
        dialed: list[str] = []

        def gai(host, port, *args, **kwargs):
            del args, kwargs
            ip = PUBLIC if host == "example.com" else OTHER
            return [_record(ip, port)]

        def dial(ip, port, timeout):
            del port, timeout
            dialed.append(ip)
            if ip == PUBLIC:
                return _pair(_http_response(302, {"Location": "https://cdn.example/a"}, b""))
            return _pair(_http_response(200, {"Content-Type": "text/html"}, b"<p>Final</p>"))

        fetched = fetch_public_url(
            "http://example.com/",
            resolver=gai,
            dial=dial,
            tls_wrap=lambda sock, host: sock,
        )
        self.assertEqual(dialed, [PUBLIC, OTHER])
        self.assertEqual(fetched.url, "https://cdn.example/a")
        self.assertEqual(fetched.body, b"<p>Final</p>")

    def test_metadata_ip_is_not_dialed(self) -> None:
        def dial(*args, **kwargs):
            raise AssertionError("dialed")

        with self.assertRaises(ValueError):
            fetch_public_url("http://169.254.169.254/latest/meta-data/", dial=dial)

    def test_oversized_body_and_declared_length_are_rejected(self) -> None:
        def gai(host, port, *args, **kwargs):
            del host, args, kwargs
            return [_record(PUBLIC, port)]

        def dial_stream(ip, port, timeout):
            del ip, port, timeout
            body = b"y" * 40
            return _pair(_http_response(200, {"Content-Type": "text/html"}, body, version="HTTP/1.0"))

        with self.assertRaises(EgressTooLarge):
            fetch_public_url("http://example.com/", resolver=gai, dial=dial_stream, max_bytes=16)

        def dial_length(ip, port, timeout):
            del ip, port, timeout
            return _pair(
                _http_response(200, {"Content-Type": "text/html", "Content-Length": "999999"}, b"")
            )

        with self.assertRaises(EgressTooLarge):
            fetch_public_url(
                "http://example.com/",
                resolver=gai,
                dial=dial_length,
                max_bytes=16,
                read_timeout=0.5,
            )

    def test_non_html_does_not_return_the_body(self) -> None:
        def dial(ip, port, timeout):
            del ip, port, timeout
            return _pair(_http_response(200, {"Content-Type": "application/pdf"}, b"SECRET-BYTES"))

        fetched = fetch_public_url(
            "http://example.com/file",
            resolver=_resolver(PUBLIC),
            dial=dial,
            require_html=True,
            max_bytes=8,
        )
        self.assertEqual(fetched.body, b"")
        self.assertNotIn("SECRET", fetched.content_type)

    def test_tls_wrap_keeps_certificate_checks_and_sets_sni(self) -> None:
        seen: dict[str, object] = {}

        class Context:
            def __init__(self) -> None:
                self.check_hostname = True
                self.verify_mode = ssl.CERT_REQUIRED

            def wrap_socket(self, sock, server_hostname=None):
                seen["sock"] = sock
                seen["sni"] = server_hostname
                seen["check"] = self.check_hostname
                seen["verify"] = self.verify_mode
                return sock

        real = ssl.create_default_context()
        self.assertTrue(real.check_hostname)
        self.assertEqual(real.verify_mode, ssl.CERT_REQUIRED)
        with patch("backend.app.security.egress_fetch.ssl.create_default_context", return_value=Context()):
            self.assertEqual(_tls_wrap("raw-sock", "example.com"), "raw-sock")  # type: ignore[arg-type]
        self.assertEqual(seen["sni"], "example.com")
        self.assertTrue(seen["check"])
        self.assertEqual(seen["verify"], ssl.CERT_REQUIRED)

    def test_slow_peer_hits_the_read_timeout(self) -> None:
        def dial(ip, port, timeout):
            del ip, port, timeout
            client, server = socket.socketpair()

            def hang() -> None:
                try:
                    server.settimeout(1)
                    server.recv(65536)
                    time.sleep(0.4)
                except OSError:
                    pass
                finally:
                    server.close()

            threading.Thread(target=hang, daemon=True).start()
            return client

        with self.assertRaises(OSError):
            fetch_public_url(
                "http://example.com/",
                resolver=_resolver(PUBLIC),
                dial=dial,
                read_timeout=0.05,
            )

    def test_concurrent_fetches_dial_their_own_ips(self) -> None:
        barrier = threading.Barrier(2)
        dialed: list[str] = []
        lock = threading.Lock()

        def gai(host, port, *args, **kwargs):
            del args, kwargs
            ip = PUBLIC if host == "one.example" else OTHER
            return [_record(ip, port)]

        def dial(ip, port, timeout):
            del port, timeout
            barrier.wait(timeout=2)
            with lock:
                dialed.append(ip)
            return _pair(_http_response(200, {"Content-Type": "text/html"}, b"<p>ok</p>"))

        errors: list[BaseException] = []
        results: list[bytes] = []

        def run(url: str) -> None:
            try:
                fetched = fetch_public_url(url, resolver=gai, dial=dial)
                results.append(fetched.body)
            except BaseException as exc:  # noqa: BLE001 - collect worker failures
                errors.append(exc)

        threads = [
            threading.Thread(target=run, args=("http://one.example/",)),
            threading.Thread(target=run, args=("http://two.example/",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(dialed), sorted([PUBLIC, OTHER]))
        self.assertEqual(results, [b"<p>ok</p>", b"<p>ok</p>"])

    def test_gzip_body_is_capped_after_decode(self) -> None:
        raw = b"a" * 200
        payload = zlib.compress(raw, wbits=16 + zlib.MAX_WBITS)
        self.assertGreater(len(raw), len(payload))

        def dial(ip, port, timeout):
            del ip, port, timeout
            return _pair(
                _http_response(
                    200,
                    {"Content-Type": "text/html", "Content-Encoding": "gzip"},
                    payload,
                )
            )

        with self.assertRaises(EgressTooLarge):
            fetch_public_url(
                "http://example.com/",
                resolver=_resolver(PUBLIC),
                dial=dial,
                max_bytes=len(payload),
            )

    def test_failed_connect_tries_the_next_validated_ip_once(self) -> None:
        calls = {"n": 0}
        dialed: list[str] = []

        def gai(host, port, *args, **kwargs):
            del host, args, kwargs
            calls["n"] += 1
            return [_record(PUBLIC, port), _record(OTHER, port)]

        def dial(ip, port, timeout):
            del port, timeout
            dialed.append(ip)
            if ip == PUBLIC:
                raise OSError("refused")
            return _pair(_http_response(200, {"Content-Type": "text/html"}, b"<p>second</p>"))

        fetched = fetch_public_url("http://example.com/", resolver=gai, dial=dial)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(dialed, [PUBLIC, OTHER])
        self.assertEqual(fetched.body, b"<p>second</p>")

    def test_too_many_redirects(self) -> None:
        def dial(ip, port, timeout):
            del ip, port, timeout
            return _pair(_http_response(302, {"Location": "/next"}, b""))

        with self.assertRaises(EgressRedirectLimit):
            fetch_public_url("http://example.com/start", resolver=_resolver(PUBLIC), dial=dial, max_hops=4)


if __name__ == "__main__":
    unittest.main()
