"""URL canonicalization and the V1 fetch wrapper."""
from __future__ import annotations

import unittest

from backend.app.research.retrieval import canonical_url, content_hash, fetch_public_html, search_public_web
from backend.app.schemas.research import SearchHit


class RetrievalTests(unittest.TestCase):
    def test_canonical_url_normalizes_host_path_and_query(self) -> None:
        self.assertEqual(
            canonical_url("HTTPS://WWW.Example.com/a/b/?b=1&a=2#section"),
            "https://example.com/a/b?a=2&b=1",
        )

    def test_content_hash_ignores_whitespace(self) -> None:
        self.assertEqual(content_hash("Widget   latency"), content_hash("Widget latency"))

    def test_blocked_url_fails_without_dialing(self) -> None:
        # Real scrape_url: egress validation rejects the literal before any socket is opened.
        result = fetch_public_html("http://127.0.0.1/secret")
        self.assertEqual(result.extraction_method, "failed")
        self.assertIn("Could not extract", result.caveat or "")

    def test_html_scrape_is_classified(self) -> None:
        def scrape(url: str) -> str:
            return "Source: https://example.com/lab\nWidget latency fell in the lab report."

        result = fetch_public_html("https://example.com/lab", scrape=scrape)
        self.assertEqual(result.extraction_method, "html")
        self.assertIn("Widget latency", result.text)
        self.assertNotIn("Source:", result.text)

    def test_search_adapter_reads_structured_hits_without_a_live_client(self) -> None:
        class FakeClient:
            def search(self, query: str, max_results: int) -> dict:
                self.query = query
                self.max_results = max_results
                return {
                    "results": [
                        {"title": "Lab", "url": "https://example.com/lab", "content": "Widget latency fell."},
                        {"title": "Skip", "url": "", "content": "no url"},
                    ]
                }

        client = FakeClient()
        hits = search_public_web("widget latency", max_results=9, client=client)
        self.assertEqual(client.max_results, 5)
        self.assertEqual(hits, [SearchHit(title="Lab", url="https://example.com/lab", snippet="Widget latency fell.")])


if __name__ == "__main__":
    unittest.main()