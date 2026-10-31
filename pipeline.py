"""Shared, resumable research orchestration for Streamlit and the CLI."""
import logging
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from groq import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError

STAGES = ("search", "reader", "writer", "critic")
STAGE_NAMES = {"search": "Search", "reader": "Read", "writer": "Write", "critic": "Review"}
logger = logging.getLogger(__name__)


class PipelinePaused(Exception):
    def __init__(self, stage, message, retry_after=0):
        super().__init__(message)
        self.stage = stage
        self.retry_after = retry_after


def retry_delay(headers):
    """Honor provider seconds or HTTP dates; fall back when headers are absent."""
    value = headers.get("retry-after")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 60
    return max(1, math.ceil(seconds)) if math.isfinite(seconds) and seconds >= 0 else 60


def execute_stage(stage, topic, state):
    # Lazy construction lets the UI load before API credentials are configured.
    from agents import build_reader_agent, build_search_agent, build_writer_chain, build_critic_chain

    if stage == "search":
        result = build_search_agent().invoke({
            "messages": [("user", f"Find recent, reliable information about: {topic}")]
        }, config={"recursion_limit": 8})
        return result["messages"][-1].content
    if stage == "reader":
        result = build_reader_agent().invoke({
            "messages": [("user", f"Research topic: {topic}\nChoose one relevant URL from these "
                          f"search results, scrape it, and summarize with its URL:\n{state['search'][:6000]}")]
        }, config={"recursion_limit": 8})
        return result["messages"][-1].content
    if stage == "writer":
        return build_writer_chain().invoke({"topic": topic, "research":
            f"SEARCH RESULTS:\n{state['search'][:6000]}\n\nDETAILED CONTENT:\n{state['reader'][:6000]}"})
    return build_critic_chain().invoke({"report": state["writer"][:16000]})


def run_research_pipeline(topic, state=None, on_progress=None):
    """Mutate this topic's state after each success. Never automatically retry."""
    topic = topic.strip()
    if not topic or len(topic) > 500:
        raise ValueError("Enter a research topic between 1 and 500 characters.")
    if state is None:
        state = {}
    for stage in STAGES:
        if stage in state:
            continue
        if on_progress:
            on_progress(stage, state)
        try:
            output = execute_stage(stage, topic, state)
            if not isinstance(output, str) or not output.strip():
                raise ValueError("The stage returned no text.")
            state[stage] = output
        except RateLimitError as exc:
            delay = retry_delay(exc.response.headers)
            logger.warning("Research paused: stage=%s status=429 retry_after=%s", stage, delay)
            raise PipelinePaused(stage,
                "Groq's shared usage limit was reached. Completed work is saved in this session. "
                "Wait for the cooldown, then resume. If the limit persists, check your Groq account quota.",
                delay) from exc
        except AuthenticationError as exc:
            raise PipelinePaused(stage, "Groq rejected the API key. Check the deployment's GROQ_API_KEY.") from exc
        except APIConnectionError as exc:
            raise PipelinePaused(stage, "Cannot reach Groq. Check connectivity, then resume.") from exc
        except APIStatusError as exc:
            logger.warning("Research paused: stage=%s provider_status=%s", stage, exc.status_code)
            raise PipelinePaused(stage, "Groq could not complete this stage. Check provider status and configuration, then resume.") from exc
        except Exception as exc:
            # Log only the type: provider/tool exception strings may contain private data.
            logger.warning("Research paused: stage=%s error_type=%s", stage, type(exc).__name__)
            raise PipelinePaused(stage, f"The {STAGE_NAMES[stage].lower()} stage could not finish. "
                                 "Completed work is saved. Check configuration and service availability, then resume.") from exc
    if on_progress:
        on_progress(None, state)
    # Preserve the original CLI function's return keys.
    return dict(zip(("search_results", "scraped_content", "report", "feedback"),
                    (state[key] for key in STAGES)))


if __name__ == "__main__":
    state = {}
    topic = input("Research topic: ")
    try:
        result = run_research_pipeline(topic, state, lambda stage, _: print(f"Stage: {stage or 'complete'}"))
        print(result["report"])
        print(result["feedback"])
    except (PipelinePaused, ValueError) as exc:
        if "writer" in state:
            print(state["writer"])
        print(str(exc))
        raise SystemExit(1)
