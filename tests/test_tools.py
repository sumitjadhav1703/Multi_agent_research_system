import socket
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from tools import scrape_url, validate_public_url


class ToolTests(unittest.TestCase):
    def test_private_and_mixed_dns_addresses_are_rejected(self):
        for addresses in (("127.0.0.1",), ("::1",), ("169.254.169.254",),
                          ("93.184.216.34", "10.0.0.1")):
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]
            with patch("tools.socket.getaddrinfo", return_value=records), self.assertRaises(ValueError):
                validate_public_url("https://example.com")

    def test_unsafe_schemes_credentials_and_ports_rejected(self):
        for url in ("file:///etc/passwd", "http://user:pass@example.com", "http://example.com:8080"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url(url)

    def test_redirect_to_private_network_is_not_fetched(self):
        response = MagicMock(status_code=302, headers={"Location": "http://127.0.0.1/"})
        response.__enter__.return_value = response
        with patch("tools.socket.getaddrinfo", side_effect=[
            [(2, 1, 6, "", ("93.184.216.34", 443))],
            [(2, 1, 6, "", ("127.0.0.1", 443))],
        ]), patch("tools.requests.get", return_value=response) as get:
            output = scrape_url.invoke({"url": "https://example.com"})
        self.assertEqual(get.call_count, 1)
        self.assertIn("Could not extract", output)

    def test_extraction_retains_source_and_removes_scripts(self):
        response = MagicMock(status_code=200, headers={"Content-Type": "text/html; charset=utf-8"})
        response.__enter__.return_value = response
        response.iter_content.return_value = [b"<p>Evidence</p><script>SECRET SCRIPT</script>"]
        with patch("tools.validate_public_url"), patch("tools.requests.get", return_value=response):
            output = scrape_url.invoke({"url": "https://example.com"})
        self.assertIn("Source: https://example.com", output)
        self.assertIn("Evidence", output)
        self.assertNotIn("SECRET", output)

    def test_connect_time_lookup_keeps_the_validated_address(self):
        public = "93.184.216.34"
        private = "127.0.0.1"
        state = {"phase": "validate"}

        def flipping(host, port, *args, **kwargs):
            del host, args, kwargs
            ip = public if state["phase"] == "validate" else private
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

        observed = []

        def fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None, **kwargs):
            del timeout, headers, allow_redirects, stream, kwargs
            state["phase"] = "connect"
            import urllib3.util.connection as urllib3_connection

            host = urlparse(url).hostname
            info = urllib3_connection.socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
            observed.append(info[0][4][0])
            response = MagicMock(status_code=200, headers={"Content-Type": "text/html"})
            response.__enter__.return_value = response
            response.iter_content.return_value = [b"<p>Pinned</p>"]
            return response

        with patch("tools.socket.getaddrinfo", side_effect=flipping), patch(
            "tools.requests.get", side_effect=fake_get
        ):
            output = scrape_url.invoke({"url": "https://example.com/page"})
            state["phase"] = "connect"
            restored = socket.getaddrinfo("example.com", 443)
        self.assertEqual(observed, [public])
        self.assertEqual(restored[0][4][0], private)
        self.assertIn("Pinned", output)
        self.assertNotIn(private, output)


if __name__ == "__main__":
    unittest.main()
