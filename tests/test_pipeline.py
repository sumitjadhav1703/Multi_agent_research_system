import unittest
from unittest.mock import patch

import httpx
from groq import RateLimitError

from pipeline import PipelinePaused, run_research_pipeline, retry_delay


class PipelineTests(unittest.TestCase):
    def test_critic_rate_limit_keeps_report_and_resume_only_calls_critic(self):
        response = httpx.Response(429, headers={"retry-after": "45"},
                                  request=httpx.Request("POST", "https://api.groq.com"))
        error = RateLimitError("private provider error", response=response, body={})
        state = {}
        with patch("pipeline.execute_stage", side_effect=["sources", "content", "report", error]) as call:
            with self.assertRaises(PipelinePaused) as caught:
                run_research_pipeline("AI agents", state)
        self.assertEqual(call.call_count, 4)
        self.assertEqual(state["writer"], "report")
        self.assertEqual(caught.exception.retry_after, 45)
        self.assertNotIn("private", str(caught.exception))
        with patch("pipeline.execute_stage", return_value="review") as call:
            result = run_research_pipeline("AI agents", state)
        call.assert_called_once_with("critic", "AI agents", state)
        self.assertEqual(result["feedback"], "review")

    def test_completed_run_makes_no_calls(self):
        state = dict.fromkeys(("search", "reader", "writer", "critic"), "saved")
        with patch("pipeline.execute_stage") as call:
            self.assertEqual(run_research_pipeline("topic", state)["report"], "saved")
        call.assert_not_called()

    def test_invalid_topics_do_not_call_provider(self):
        for topic in ("", "  ", "x" * 501):
            with self.subTest(topic=topic[:10]), patch("pipeline.execute_stage") as call:
                with self.assertRaises(ValueError):
                    run_research_pipeline(topic)
                call.assert_not_called()

    def test_other_failure_is_safe_and_preserves_completed_stage(self):
        state = {"search": "sources"}
        with patch("pipeline.execute_stage", side_effect=RuntimeError("secret")):
            with self.assertRaises(PipelinePaused) as caught:
                run_research_pipeline("topic", state)
        self.assertEqual(caught.exception.stage, "reader")
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(state, {"search": "sources"})

    def test_retry_header_is_conservative(self):
        for value in ("nan", "inf", "invalid", "-1", None):
            self.assertEqual(retry_delay({"retry-after": value}), 60)
        self.assertEqual(retry_delay({"retry-after": "1.2"}), 2)


if __name__ == "__main__":
    unittest.main()
