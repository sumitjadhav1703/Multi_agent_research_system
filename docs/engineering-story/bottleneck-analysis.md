# Bottleneck analysis (V1 → V2)

Every row is grounded in V1 source under `/workspace` unless marked otherwise. No invented bottlenecks.

**V1 freeze:** tag `v1-baseline` @ `f1881b9` · baseline doc [`../BASELINE_REPORT.md`](../BASELINE_REPORT.md)

---

## Summary table

| # | Bottleneck | Original behavior | Root cause | Evidence | Impact | Proposed fix | Trade-off | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Sequential stages | `for stage in STAGES` | Simple pipeline design | `v1/pipeline.py` `run_research_pipeline` | Latency = sum of stages | LangGraph `Send` ≤2 workers | More provider load | **IMPLEMENTED** (V2) |
| 2 | Search breadth ≤5 | `max_results=5` | Tavily call hard-coded | `v1/tools.py` `web_search` | Limited candidate pool | Multi-query + caps (V2 ≤3 results × ≤4 searches) | More Tavily quota | **IMPLEMENTED** (re-bounded) |
| 3 | One source read | Reader prompt “Read one relevant source URL” | Agent design | `v1/agents.py` `build_reader_agent` | Thin evidence | Multi-source ledger ≤6 | Fetch cost/RAM | **IMPLEMENTED** |
| 4 | Limited HTML extract | 1 MB body, 6k text; strip chrome | Safety/cost | `v1/tools.py` `scrape_url` | Truncated pages | Keep bounds; passages ≤500 chars | Incomplete long docs | **PARTIALLY** (bounds kept) |
| 5 | No PDF support | Non-HTML Content-Type rejected | No PDF deps | `v1/tools.py`; `v1/requirements.in` | Academic PDFs unusable | Optional PDF later | CPU/RAM on Free | **DEFERRED** (`pdf_enabled=False`) |
| 6 | No structured evidence | Writer sees free text blobs | No schema | `pipeline` return keys | Weak citations | Passages + claims tables | Schema complexity | **IMPLEMENTED** |
| 7 | No claim-level verify | Critic is prose review | Same LLM, no passage IDs | `v1/agents.py` critic prompt | False confidence | Overlap + citation checks | Misses paraphrase support | **IMPLEMENTED** (assessed, not absolute) |
| 8 | Critic = same model | One `build_llm` | Single Groq path | `v1/agents.py` `build_llm` | Correlated errors | Role aliases + free fallbacks | Multi-key ops | **IMPLEMENTED** |
| 9 | No quality benchmarks | No golden set in V1 | Scope | Absent under V1 | Cannot prove improvement | DeepEval + fixtures | Eval cost | **PARTIALLY** (harness; scores NOT MEASURED) |
| 10 | In-memory state | `session_state` / dict | Streamlit model | `v1/app.py` L17–22, L154, L183 | Restart/session loss | Neon jobs + checkpoints | DB dependency | **IMPLEMENTED** (V2) |
| 11 | Interrupted jobs lost | No durable queue | No Postgres | Absence in V1 | Demo fragility | Lease + consumer | At-least-once LLM | **IMPLEMENTED** |
| 12 | Shared provider rate limits | One Groq model; `max_retries=0` | Free-tier + UI owns pause | `v1/agents.py`; `PipelinePaused` | User cooldown UX | Multi-provider allowlist failover | Fallback still free-only | **IMPLEMENTED** (partial live verify) |
| 13 | No global inference budgets | Unlimited starts if keys present | No server quota | V1 `v1/app.py` | Abuse / bill risk | One-use guest + daily/active caps | Cookie ≠ human | **IMPLEMENTED** (V2) |
| 14 | No multi-user quota coord | Single browser session | No identity store | V1 | Cannot host public demo safely | `guest_identities` + Turnstile | Privacy/UX friction | **IMPLEMENTED** |
| 15 | No persistent job mgmt | Sync script in Streamlit | Architecture | `v1/app.py` run path | Blocks UI; no replay | REST 202 + job row + SSE | More moving parts | **IMPLEMENTED** |
| 16 | Streamlit UX limits | One-page tabs | Product choice | `v1/app.py` | Not a research workspace | React six-screen console | Frontend maintenance | **IMPLEMENTED** |
| 17 | No live execution stream | `st.status` callbacks only | Streamlit pattern | `v1/app.py` `render_progress` | Refresh loses timeline | SSE + event log | Connection handling | **IMPLEMENTED** |
| 18 | Limited observability | Basic logging | Scope | V1 | Hard to debug demos | OTEL + JSON logs | Export off by default | **PARTIALLY** |
| 19 | Prompt injection | Untrusted web text in prompts | LLM apps | Mitigated by wording in `v1/agents.py`; V2 delimiters | Tool misuse / spoofed claims | Fixed tool ports; injection fixtures | Residual LLM risk | **PARTIALLY** |
| 20 | SSRF residual | DNS/scheme + connect pin | No egress proxy | `v1/tools.py` comments; RISK R04 | Internal network risk | Egress proxy follow-up | Infra complexity | **UNRESOLVED** |
| 21 | CPU/RAM constraints | Streamlit Cloud / later Render Free 0.1 CPU 512 MB | Free hosting | Render docs 2026-11-08 | OOM / slow | Bounds + one worker | No HA | **ONGOING** |
| 22 | Free-tier sleep | N/A in V1 Streamlit Cloud; V2 Render Free ~15 min idle | Host policy | [Render free](https://render.com/docs/free) | ~1 min cold start | Neon durable state; document cold start | Demo UX | **ACCEPTED** (NOT MEASURED locally) |

---

## Detailed evidence notes

### Sequential execution

```62:71:pipeline.py
# (conceptual) for stage in STAGES: execute_stage(...)
```

`run_research_pipeline` skips completed keys for resume but never overlaps stages. V2 fan-out is only inside the research wave (search/fetch workers), not “all agents at once.”

### One-source reader

Reader system prompt explicitly asks for one URL. There is no hard scrape counter, but writer context is built from search text + that one scrape. Impact on citation diversity is structural.

### Critic honesty (already disclosed in V1)

Critic prompt states the review is not independent fact-checking. Bottleneck is product trust: users may still treat critic text as verification. V2 replaces this with passage-linked claim status and UI copy “evidence assessed.”

### In-memory resume

V1 resume after `RateLimitError` is real and tested (`tests/test_app.py`, `tests/test_pipeline.py`). It does **not** survive process restart or a new browser session. That distinction drove Milestone 3.

### Metrics gap

Live V1 search/model call counts, tokens, and latency are **NOT MEASURED** (baseline report §6). Bottleneck severity for wall-clock is therefore qualitative from architecture, not from a recorded p95 table.

---

## What V2 did **not** fix yet

- SSRF without egress proxy  
- Exactly-once provider execution  
- PDF parsing  
- Measured DeepEval V1 vs V2 quality delta  
- Measured Render cold-start / RSS  

These remain open in [`../RISK_REGISTER.md`](../RISK_REGISTER.md) and [`../IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).
