import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def test_landing_page_works_without_keys(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "TAVILY_API_KEY": ""}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("GROQ_API_KEY" in item.value for item in app.warning))

    def test_example_fills_topic(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        app.button(key="example_0").click().run()
        self.assertEqual(app.text_input(key="topic_input").value, "How are AI agents being evaluated?")

    def test_interrupted_run_can_be_resumed(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        app.session_state["results"] = {"search": "Saved sources"}
        app.session_state["run_topic"] = "Original topic"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["failed_stage"], "reader")
        self.assertTrue(app.button(key="resume_research"))

    def test_report_survives_failure_and_reruns_do_not_restart(self):
        import httpx
        from groq import RateLimitError
        error = RateLimitError("private detail", body={}, response=httpx.Response(
            429, headers={"retry-after": "60"}, request=httpx.Request("POST", "https://api.groq.com")))
        with patch.dict(os.environ, {"GROQ_API_KEY": "test", "TAVILY_API_KEY": "test"}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
            app.text_input(key="topic_input").set_value("AI agents")
            with patch("pipeline.execute_stage", side_effect=["sources", "content", "# Saved report", error]) as call:
                app.button(key="start_research").click().run()
            self.assertEqual(call.call_count, 4)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["results"]["writer"], "# Saved report")
            with patch("pipeline.execute_stage") as call:
                app.run()
                app.button(key="resume_research").click().run()
            call.assert_not_called()
            app.session_state["retry_at"] = 0
            with patch("pipeline.execute_stage", return_value="Review complete") as call:
                app.button(key="resume_research").click().run()
            self.assertEqual(call.call_count, 1)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["results"]["critic"], "Review complete")


if __name__ == "__main__":
    unittest.main()
