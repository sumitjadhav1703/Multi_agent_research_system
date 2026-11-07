"""Usage extraction must not invent zeros."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.app.providers.usage import extract_usage


class UsageTests(unittest.TestCase):
    def test_missing_usage_is_unknown(self) -> None:
        usage = extract_usage(SimpleNamespace(choices=[]))
        self.assertTrue(usage.is_unknown)
        self.assertIsNone(usage.prompt_tokens)
        self.assertIsNone(usage.total_tokens)

    def test_partial_usage_preserves_none(self) -> None:
        usage = extract_usage(
            SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=None, total_tokens=None))
        )
        self.assertEqual(usage.prompt_tokens, 10)
        self.assertIsNone(usage.completion_tokens)
        self.assertIsNone(usage.total_tokens)

    def test_dict_usage(self) -> None:
        usage = extract_usage({"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})
        self.assertEqual(usage.total_tokens, 3)


if __name__ == "__main__":
    unittest.main()
