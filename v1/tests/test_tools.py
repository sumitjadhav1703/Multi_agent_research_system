import socket
import threading
import unittest
from unittest.mock import patch

from tools import scrape_url, validate_public_url

PUBLIC = "93.184.216.34"
_GA = "backend.app.security.egress_fetch.socket.getaddrinfo"
_DIAL = "backend.app.security.egress_fetch._dial_ip"
_TLS = "backend.app.security.egress_fetch._tls_wrap"


def _record(ip, port=443):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))


def _http_response(status, headers, body):
    lines = [f"HTTP/1.1 {status} OK"]
    lowered = {key.lower() for key in headers}
    for key, value in headers.items():
        lines.append(f"{key}: {value}")
    if "content-length" not in lowered:
        lines.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def _pair(payload, sink=None):
    client, server = socket.socketpair()

    def serve():
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


class ToolTests(unittest.TestCase):
    def test_private_and_mixed_dns_addresses_are_rejected(self):
        for addresses in (("127.0.0.1",), ("::1",), ("169.254.169.254",), (PUBLIC, "10.0.0.1")):
            records = [_record(ip) for ip in addresses]
            with patch(_GA, return_value=records), self.assertRaises(ValueError):
                validate_public_url("https://example.com")

    def test_unsafe_schemes_credentials_and_ports_rejected(self):
        for url in ("file:///etc/passwd", "http://user:pass@example.com", "http://example.com:8080"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url(url)

    def test_metadata_literals_are_rejected_before_dial(self):
        def dial(*args, **kwargs):
            raise AssertionError("dialed a metadata address")

        for url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://2130706433/",
            "http://[::ffff:169.254.169.254]/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ):
            with self.subTest(url=url), patch(_DIAL, side_effect=dial):
                with self.assertRaises(ValueError):
                    validate_public_url(url)
                output = scrape_url.invoke({"url": url})
            self.assertIn("Could not extract", output)

    def test_redirect_to_private_network_is_not_fetched(self):
        dialed = []

        def gai(host, port, *args, **kwargs):
            del args, kwargs
            ip = PUBLIC if host == "example.com" else "10.0.0.9"
            return [_record(ip, port)]

        def dial(ip, port, timeout):
            del port, timeout
            dialed.append(ip)
            if ip != PUBLIC:
                raise AssertionError(ip)
            return _pair(_http_response(302, {"Location": "http://10.0.0.9/secret"}, b"SECRET"))

        with patch(_GA, side_effect=gai), patch(_DIAL, side_effect=dial), patch(_TLS, side_effect=lambda sock, host: sock):
            output = scrape_url.invoke({"url": "https://example.com"})
        self.assertEqual(dialed, [PUBLIC])
        self.assertIn("Could not extract", output)
        self.assertNotIn("SECRET", output)

    def test_extraction_retains_source_and_removes_scripts(self):
        def dial(ip, port, timeout):
            del ip, port, timeout
            body = b"<p>Evidence</p><script>SECRET SCRIPT</script>"
            return _pair(_http_response(200, {"Content-Type": "text/html; charset=utf-8"}, body))

        with patch(_GA, return_value=[_record(PUBLIC)]), patch(_DIAL, side_effect=dial), patch(_TLS, side_effect=lambda sock, host: sock):
            output = scrape_url.invoke({"url": "https://example.com"})
        self.assertIn("Source: https://example.com", output)
        self.assertIn("Evidence", output)
        self.assertNotIn("SECRET", output)

    def test_dns_rebind_dials_the_validated_address(self):
        calls = {"n": 0}
        dialed = []
        seen = []

        def gai(host, port, *args, **kwargs):
            del host, args, kwargs
            calls["n"] += 1
            ip = PUBLIC if calls["n"] == 1 else "127.0.0.1"
            return [_record(ip, port)]

        def dial(ip, port, timeout):
            del port, timeout
            dialed.append(ip)
            body = b"<p>Pinned</p>"
            return _pair(_http_response(200, {"Content-Type": "text/html"}, body), seen)

        original = socket.getaddrinfo
        with patch(_GA, side_effect=gai), patch(_DIAL, side_effect=dial), patch(_TLS, side_effect=lambda sock, host: sock):
            output = scrape_url.invoke({"url": "https://example.com/page"})
        self.assertEqual(calls["n"], 1)
        self.assertEqual(dialed, [PUBLIC])
        self.assertIn(b"Host: example.com\r\n", seen[0])
        self.assertNotIn(b"127.0.0.1", seen[0])
        self.assertIn("Pinned", output)
        self.assertNotIn("127.0.0.1", output)
        self.assertIs(socket.getaddrinfo, original)

    def test_oversized_body_is_not_extracted(self):
        def dial(ip, port, timeout):
            del ip, port, timeout
            body = b"<p>" + (b"a" * 80) + b"</p>"
            return _pair(_http_response(200, {"Content-Type": "text/html"}, body))

        with patch(_GA, return_value=[_record(PUBLIC, 80)]), patch(_DIAL, side_effect=dial), patch(
            "tools._MAX_BODY_BYTES", 32
        ):
            output = scrape_url.invoke({"url": "http://example.com/big"})
        self.assertIn("exceeds the extraction limit", output)
        self.assertNotIn("aaaa", output)


if __name__ == "__main__":
    unittest.main()
