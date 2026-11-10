"""ResearchMind's Streamlit workspace."""
import math
import os
import time
from html import escape
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from pipeline import PipelinePaused, STAGES, STAGE_NAMES, run_research_pipeline

load_dotenv()
st.set_page_config(page_title="ResearchMind · Research workspace", page_icon="🔬", layout="wide")
st.markdown(f"<style>{Path(__file__).with_name('style.css').read_text()}</style>", unsafe_allow_html=True)

for key, default in {
    "results": {}, "run_topic": "", "error": "", "failed_stage": "", "retry_at": 0,
    "elapsed": 0, "topic_input": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default
state = st.session_state
if state.results and len(state.results) < len(STAGES) and not state.error:
    state.failed_stage = next(stage for stage in STAGES if stage not in state.results)
    state.error = "Research stopped before all stages finished. Resume to continue from the saved work."

# Streamlit Cloud supports root-level secrets; local development uses .env.
for key in ("GROQ_API_KEY", "TAVILY_API_KEY"):
    if not os.environ.get(key):
        try:
            if st.secrets.get(key):
                os.environ[key] = str(st.secrets[key])
        except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            pass
missing = [key for key in ("GROQ_API_KEY", "TAVILY_API_KEY") if not os.environ.get(key)]

st.markdown('''<div class="brand-bar"><div class="brand">Research<span>Mind</span></div>
<div class="brand-detail">A multi-agent research workspace</div></div>
<div class="intro"><h1>A question.<br>A clearer <span class="focus-word">perspective.</span></h1>
<p>Search the web, explore a source, and turn the evidence into a report.
Follow each stage from the first search to the final critique.</p></div>''', unsafe_allow_html=True)

if missing:
    st.warning("Setup required: add " + " and ".join(missing) +
               " to Streamlit Cloud → App settings → Secrets, or your local .env file.")

left, right = st.columns([1.35, 1], gap="large")
with left:
    with st.container(border=True, key="research_input"):
        st.subheader("What are you researching?")
        st.caption("Start with a focused question, a technology, or an emerging trend.")
        with st.form("research_form", border=False):
            st.text_input("Research topic", key="topic_input", max_chars=500,
                          placeholder="e.g. What makes AI agents reliable in production?")
            submitted = st.form_submit_button("Start research", type="primary", key="start_research",
                                             use_container_width=True, disabled=bool(missing))
        st.caption("Four stages · Web sources · Markdown export")
    st.caption("NEED A STARTING POINT?")
    examples = [("AI agent evaluation", "How are AI agents being evaluated?"),
                ("CRISPR therapies", "What are the current challenges for CRISPR therapies?"),
                ("Fusion energy", "What are the main barriers to practical fusion energy?")]

    def choose_example(value):
        state.topic_input = value

    with st.container(key="examples"):
        columns = st.columns(3)
        for i, (label, question) in enumerate(examples):
            columns[i].button(label, key=f"example_{i}", on_click=choose_example, args=(question,),
                              use_container_width=True)

with right:
    st.subheader("The research process")
    progress_area = st.empty()


def render_progress(active=None):
    descriptions = {"search": "Find relevant web sources", "reader": "Extract a source in depth",
                    "writer": "Synthesize findings with citations", "critic": "Assess the report's quality"}
    rows = []
    for i, stage in enumerate(STAGES, 1):
        if stage in state.results:
            status, css = "Complete", "complete"
        elif stage == active:
            status, css = "Working", "active"
        elif stage == state.failed_stage:
            status, css = "Paused", "paused"
        else:
            status, css = "Waiting", "waiting"
        rows.append(f'<div class="process-row {css}"><span class="step-index">{i:02}</span>'
                    f'<div class="step-copy"><strong>{STAGE_NAMES[stage]}</strong>'
                    f'<span>{descriptions[stage]}</span></div><span class="step-status">{status}</span></div>')
    progress_area.markdown('<div class="process">' + ''.join(rows) + '</div>', unsafe_allow_html=True)


resume = False
if state.error:
    with st.container(border=True, key="recovery"):
        st.subheader(f"{STAGE_NAMES[state.failed_stage]} paused")
        st.warning(state.error)
        remaining = max(0, math.ceil(state.retry_at - time.time()))
        if remaining:
            st.caption(f"Provider cooldown: about {remaining} seconds remaining. Resume checks the cooldown before making a request.")
        st.caption(f"Resuming uses the saved topic: {state.run_topic}")
        resume = st.button("Resume unfinished stages", key="resume_research", disabled=bool(missing))

render_progress()
should_run = False
if submitted:
    topic = state.topic_input.strip()
    if not topic:
        st.warning("Enter a research topic first.")
    elif time.time() < state.retry_at:
        st.warning("The Groq cooldown is still active. Your previous work is saved; wait before starting or resuming.")
    else:
        state.results = {}
        state.run_topic = topic
        state.error = ""
        state.failed_stage = ""
        state.elapsed = 0
        should_run = True
elif resume:
    if time.time() < state.retry_at:
        st.info("The cooldown is still active. Wait a little longer, then select Resume unfinished stages.")
    else:
        state.error = ""
        state.failed_stage = ""
        should_run = True

if should_run:
    started = time.monotonic()
    try:
        with st.status("Research in progress", expanded=True) as status:
            def update(stage, results):
                render_progress(stage)
                if stage:
                    status.update(label=f"{STAGE_NAMES[stage]} · {len(results)} of 4 stages complete")
                    st.write(f"{STAGE_NAMES[stage]} stage started")
            run_research_pipeline(state.run_topic, state.results, update)
            status.update(label="Research complete · 4 of 4 stages", state="complete", expanded=False)
    except PipelinePaused as exc:
        state.error = str(exc)
        state.failed_stage = exc.stage
        state.retry_at = time.time() + exc.retry_after
    finally:
        state.elapsed += time.monotonic() - started
    st.rerun()

if state.results:
    st.divider()
    st.subheader("Your research")
    st.markdown(f"**{escape(state.run_topic)}**")
    st.caption(f"{len(state.results)} of 4 stages complete · {state.elapsed:.0f}s active time · Saved for this browser session")
    report_tab, review_tab, evidence_tab = st.tabs(["Report", "Critic review", "Source material"])
    with report_tab:
        if "writer" in state.results:
            if "critic" not in state.results:
                st.info("Your draft is ready to read and download. The critic review is still pending.")
            with st.container(key="report_body"):
                st.markdown(state.results["writer"])
            st.download_button("Download report", state.results["writer"],
                               file_name="researchmind-report.md", mime="text/markdown", key="download_report")
        else:
            st.info("The report will appear after the writing stage. Saved findings are available in Source material.")
    with review_tab:
        if "critic" in state.results:
            st.caption("An AI assessment of the draft, not independent verification of its claims.")
            st.markdown(state.results["critic"])
        else:
            st.info("The critic review will appear when the final stage completes.")
    with evidence_tab:
        for stage, title in (("search", "Search findings"), ("reader", "Source excerpt and summary")):
            if stage in state.results:
                with st.expander(title, expanded=True):
                    st.markdown(state.results[stage])
else:
    st.divider()
    st.markdown('''<div class="empty-state"><h2>From scattered sources to a structured report.</h2>
<p>Your report, critique, and source material will appear here once research begins.</p></div>''', unsafe_allow_html=True)

st.markdown('''<div class="app-footer"><span>ResearchMind</span><span>Powered by Groq, Tavily &amp; LangChain</span></div>''', unsafe_allow_html=True)
st.caption("AI-generated research can contain errors. Check original sources before relying on a claim. Session results are lost when the session expires; download reports you want to keep.")
