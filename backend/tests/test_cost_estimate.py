"""List-price token×rate cost estimate."""
from __future__ import annotations

import unittest

from backend.app.cost_estimate import (
    INPUT_USD_PER_MTOK,
    OUTPUT_USD_PER_MTOK,
    SEARCH_USD_PER_CALL,
    estimate_usage_cost_usd,
    refresh_estimated_cost,
)


class CostEstimateTests(unittest.TestCase):
    def test_unknown_when_no_counters(self) -> None:
        self.assertIsNone(estimate_usage_cost_usd())

    def test_token_formula_matches_published_rates(self) -> None:
        # (1_000_000 * 0.10 + 500_000 * 0.40) / 1e6 = 0.10 + 0.20 = 0.30
        self.assertEqual(
            estimate_usage_cost_usd(prompt_tokens=1_000_000, completion_tokens=500_000),
            "0.300000",
        )
        expected = (140 / 1_000_000) * INPUT_USD_PER_MTOK + (656 / 1_000_000) * OUTPUT_USD_PER_MTOK
        self.assertEqual(
            estimate_usage_cost_usd(prompt_tokens=140, completion_tokens=656),
            f"{expected:.6f}",
        )

    def test_search_calls_add_list_rate(self) -> None:
        self.assertEqual(
            estimate_usage_cost_usd(search_calls=4),
            f"{4 * SEARCH_USD_PER_CALL:.6f}",
        )

    def test_refresh_writes_usage_field(self) -> None:
        usage = refresh_estimated_cost(
            {"prompt_tokens": 1000, "completion_tokens": 500, "search_calls": 2}
        )
        self.assertIsNotNone(usage["estimated_cost_usd"])
        self.assertEqual(
            usage["estimated_cost_usd"],
            estimate_usage_cost_usd(prompt_tokens=1000, completion_tokens=500, search_calls=2),
        )


if __name__ == "__main__":
    unittest.main()
