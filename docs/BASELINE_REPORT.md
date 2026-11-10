# ResearchMind V1 — Baseline Report

> **Historical record (2026-11-07, commit `f1881b9`).** Describes V1 as it was when frozen, when V1 files sat at the repo root. Today V1 lives in `v1/` (run `streamlit run v1/app.py`; tests: `cd v1 && python -m unittest discover -s tests`, 16 tests as of 2026-11-10), is not deployed, and `.cursor/` / `.impeccable/` / `CURSOR_IMPLEMENTATION_PLAN.md` are no longer in the repo. Current docs: [`README.md`](../README.md), [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md). The tree and commands below show the root layout at freeze time.

**Date:** 2026-11-07  
**Commit:** `f1881b9` — *Merge pull request #5 from sumitjadhav1703/docs/professional-readme*  
**Freeze tag:** `v1-baseline` (annotated, Milestone 0)  
**Branch:** `main` (tracks `origin/main` at clone; local uncommitted V2 kit/M1 work may exist)  
**Auditor note:** Parent session was Cursor Auto/Composer, not Opus 5.5 High. Sonnet 5 coding agents were unavailable due to weekly usage.

---

## 1. Runtime and dependency baseline

| Item | Value |
|---|---|
| CI Python | 3.13 (`.github/workflows/tests.yml`) |
| Local audit Python | 3.15.2 (`Clang 21.0.0`) |
| Install | `python -m pip install -r requirements.txt` into `/tmp/rm_v1_venv` |
| Lock style | `uv pip compile requirements.in → requirements.txt` (pinned) |
| Direct deps (`requirements.in`) | streamlit, langchain, langchain-core, langchain-groq, langgraph, groq, tavily-python, beautifulsoup4, requests, python-dotenv |
| Notable locked versions | `streamlit==1.66.1`, `langchain==1.4.7`, `langgraph==1.2.19`, `langchain-groq==1.1.3`, `groq==0.37.1`, `tavily-python==0.8.5` |
| Secrets template | `.env.example` → `GROQ_API_KEY`, `TAVILY_API_KEY` only |

**Decision for V2:** Prefer CI’s Python **3.13** for Docker/Render; do not treat local 3.15 as the deployment target without an explicit ADR.

---

## 2. Offline test results (exact)

```text
Command: /tmp/rm_v1_venv/bin/python -m unittest discover -s tests -v
Exit code: 0
Ran 13 tests in 0.582s
OK
```

| Suite | Tests | Result |
|---|---|---|
| `tests/test_app.py` | 4 | Pass |
| `tests/test_pipeline.py` | 5 | Pass |
| `tests/test_tools.py` | 4 | Pass |
| **Total** | **13** | **13 pass / 0 fail / 0 skip** |

Coverage observed (behavioral, not line coverage):

- Landing page without API keys  
- Example topic fill  
- Interrupted run resume UX  
- Rate-limit pause preserves writer output; resume does not restart completed stages  
- Invalid topics never call providers  
- SSRF private/mixed DNS rejection; redirect-to-private blocked; script stripping  

**Not run:** live Groq/Tavily end-to-end research. **No live metrics invented.**

Frontend/build checks: none (Streamlit app; no Vite/React yet).

CI reproducibility: yes for offline suite — no secrets required. Matches workflow:

```yaml
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

---

## 3. Current application behavior (V1)

**Entry points**

- Streamlit UI: `app.py`  
- CLI: `pipeline.py` `__main__`  
- Public demo URL (README): `https://multiagentresearchsystem-f47mjoqmqw8nlxf8uud5v2.streamlit.app/` (existence not re-probed in this audit)

**Pipeline stages** (`pipeline.STAGES`): `search` → `reader` → `writer` → `critic`

**Models:** all stages use Groq `openai/gpt-oss-20b` via `langchain_groq.ChatGroq` (`agents.build_llm`).

**Tools**

- `web_search` — Tavily, max 5 results  
- `scrape_url` — bounded HTML fetch with DNS public-IP checks, manual redirects (≤4), 1 MB cap, script/style strip (as frozen; V1 `v1/tools.py` now uses the shared `backend/app/security/egress_fetch.py`)  

**State:** in-memory / Streamlit `session_state` only. Successful stage outputs retained for resume after `PipelinePaused`. No PostgreSQL, no durable job queue.

**Orchestration:** sequential Python loop in `run_research_pipeline`; search/reader use LangChain `create_agent` (LangGraph is a transitive/direct dependency but V1 does **not** implement the approved V2 `StateGraph` with fan-out, evidence ledger, or human revision node).

---

## 4. Repository map

```text
.
├── app.py                 # Streamlit ResearchMind workspace
├── agents.py              # Groq LLM + search/reader agents + writer/critic chains
├── pipeline.py            # Shared resumable stage orchestration + CLI
├── tools.py               # Tavily search + SSRF-aware scrape
├── style.css              # Dark/orange Streamlit styling
├── requirements.in / .txt
├── .env.example
├── .streamlit/config.toml
├── .github/workflows/tests.yml
├── assets/                # Screenshots
├── tests/                 # unittest (mocked providers)
├── docs/
│   ├── repair-plan.md     # V1 reliability/UI repair notes
│   └── RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md  # V2 approved plan (from kit)
├── CURSOR_IMPLEMENTATION_PLAN.md
└── .cursor/agents/        # Sonnet 5 specialist agent defs (from kit)
```

**Absent (expected for V1):** `Dockerfile`, `render.yaml`, FastAPI package, React/Vite app, LiteLLM config, DeepEval suite, Neon migrations, Cloudflare Worker, Redis/pgvector.

---

## 5. Reusable V1 inventory (preserve)

| Symbol | File | Reuse intent |
|---|---|---|
| `validate_public_url` | `tools.py` | Basis for V2 SSRF policy (extend with connect-time pinning) |
| `scrape_url` / HTML bounds | `tools.py` | Wrap into allowlisted tool for LangGraph workers |
| `web_search` | `tools.py` | Wrap behind per-run search budget |
| `STAGES` / resume semantics | `pipeline.py` | Behavioral baseline for comparison; not the V2 graph |
| `PipelinePaused` + safe errors | `pipeline.py` | Pattern for non-leaking provider failures |
| `retry_delay` | `pipeline.py` | Honor `Retry-After` |
| Prompt “untrusted content” wording | `agents.py` | Carry into V2 system prompts |
| Offline SSRF + resume tests | `tests/` | Keep green while V2 lands beside V1 |
| Streamlit path | `app.py` | Preserve as ResearchMind V1 baseline until V2 gates pass |

---

## 6. Live / quality metrics

| Metric | Status |
|---|---|
| Per-run search/model call counts | **Not measured** (no live run) |
| Token usage | **Not measured** |
| Latency | **Not measured** |
| Citation accuracy (manual) | **Not measured** |
| Streamlit Cloud cold-start | **Not measured** in this session |

When credentials exist, Milestone 0 should capture a small controlled dataset through V1 only and store sanitized artifacts under `docs/evals/` / `output/` (gitignored where needed).

---

## 7. Known V1 gaps vs approved V2 plan

Already documented in README and source of truth; confirmed in code:

- One source read, not multi-source evidence ledger  
- Critic ≠ claim verification against passages  
- Single Groq model; no LiteLLM free-only failover  
- No auth, one-use quota, global concurrency cap  
- No Postgres jobs/events/checkpoints  
- No React Research Console / SSE replay  
- No DeepEval harness  
- No remote MCP  
- No Render/Neon/Vercel deployment profile for V2 topology  

---

## 8. Baseline commands to re-run

```bash
python3.13 -m venv .venv   # prefer 3.13 to match CI
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```
