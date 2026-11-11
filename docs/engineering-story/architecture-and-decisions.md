# Architecture and technology decisions

**Verification date for external docs:** 2026-11-08  
**Last verified:** 2026-11-10 (branch `fix/audit-hardening`)  
**Related ADRs:** [`../ADR/0001-approved-architecture.md`](../ADR/0001-approved-architecture.md) through [`0006`](../ADR/0006-cloudflare-mcp.md) (ADR 0005 streaming/hosting write-up is **missing** — numbering jumped to 0006).

For every major choice: problem → selection → alternatives rejected → performance/cost/infra → limitations → status in this repo.

---

## Backend and orchestration

### FastAPI — IMPLEMENTED · VERIFIED

| | |
|---|---|
| **Problem** | Need a typed HTTP API for jobs, quotas, SSE, and MCP forwarding; Streamlit cannot own durable multi-client APIs. |
| **Why selected** | Async-friendly ASGI, OpenAPI, dependency injection, fits Uvicorn on Render Docker. |
| **Alternatives** | Flask/Django sync apps; keep Streamlit as the only surface. |
| **Rejected because** | Sync frameworks fight SSE/long jobs; Streamlit is not a multi-tenant job API. |
| **Perf** | One Uvicorn worker (`WEB_CONCURRENCY=1`) to keep lease ownership simple. |
| **Cost** | No extra process vs a separate ASGI gateway. |
| **Infra** | Python 3.13 slim image (`Dockerfile`). |
| **Limits** | Single worker is not horizontal scale. |
| **Evidence** | `backend/app/main.py`, `backend/tests/test_health_api.py`, `test_cors.py`. |

### LangGraph — IMPLEMENTED · VERIFIED

| | |
|---|---|
| **Problem** | V1 sequential agents lack bounded fan-out, interruptible human review, and checkpointed resume. |
| **Why selected** | First-party graph, `Send` for fan-out, `interrupt` for review, Postgres checkpointer support. |
| **Alternatives** | Hand-rolled asyncio tasks; CrewAI/AutoGen-style agent swarms; keep LangChain `create_agent` only. |
| **Rejected because** | Swarms are hard to bound and eval; hand-rolled loses checkpoint/interrupt; V1 agents cannot express evidence gate + revision policy cleanly. |
| **Perf** | ≤2 parallel workers avoids free-tier stampede. |
| **Cost** | More model calls than V1 when fan-out is used; ceilings clamp spend. |
| **Evidence** | `backend/app/graph/*`, ADR 0003, `test_graph_workflow.py`. |

### Pydantic / pydantic-settings — IMPLEMENTED · VERIFIED

Typed request/response schemas and fail-closed settings (`ALLOW_PAID_MODELS`, allowlist, Turnstile URL). Alternatives (plain dicts, dynaconf) rejected for weaker validation at boot.

### Async processing — PARTIALLY IMPLEMENTED

FastAPI is async; the graph runner uses the sync graph API (`stream`) with a sync Postgres saver inside the lifespan consumer thread (`docs/IMPLEMENTATION_STATUS.md` M3). Full async end-to-end graph execution is **not** the current path.

### PostgreSQL (Neon) — IMPLEMENTED · VERIFIED (local) · live wired

| | |
|---|---|
| **Problem** | Ephemeral Render disk + Streamlit session cannot own jobs, quotas, events, evidence. |
| **Why selected** | Relational durability, `FOR UPDATE SKIP LOCKED`, LangGraph Postgres checkpointer. |
| **Alternatives** | Redis queue; SQLite on disk; Render Postgres free (30-day expiry). |
| **Rejected because** | Redis is another billable service; local SQLite fails on spin-down; Render free Postgres expires ([Render free docs](https://render.com/docs/free)). Neon free is ongoing with CU-hour/storage caps ([Neon plans](https://neon.com/docs/introduction/plans), verified 2026-11-08). |
| **Evidence** | `backend/migrations/0001_identity_jobs_quota.sql`, `test_postgres_durability.py`, deployment report. |

### Persistent checkpoints — IMPLEMENTED · VERIFIED locally

`AsyncPostgresSaver.setup()` + sync `PostgresSaver` for worker invoke. SQLite test mode keeps graph saver in memory. Neon-specific checkpointer proof is **NOT MEASURED** in docs (local throwaway Postgres only).

### PostgreSQL-backed queue — IMPLEMENTED · VERIFIED

One lifespan `QueueConsumer` leases jobs with `FOR UPDATE SKIP LOCKED`. No separate worker service on Free. Alternative (Render Background Worker) rejected for student cost and Free plan constraints.

### SSE — IMPLEMENTED · VERIFIED

`GET /api/v1/research-runs/{id}/events/stream` with `Last-Event-ID` replay. WebSockets deferred (see streaming doc).

---

## LLM infrastructure

### LiteLLM SDK Router — IMPLEMENTED · VERIFIED (mock)

| | |
|---|---|
| **Problem** | Unify providers (now Groq, OpenRouter, NVIDIA NIM; Gemini/Mistral dropped 2026-11-11) behind role aliases with free-first failover and an owner-approved paid Meta last resort. |
| **Why selected** | In-process Router; fallbacks; OpenAI-shaped API ([LiteLLM docs](https://docs.litellm.ai/), verified 2026-11-08). |
| **Alternative: LiteLLM Proxy** | Separate gateway process with its own RAM/ops. |
| **Rejected Proxy because** | Render Free has 512 MB RAM / 0.1 CPU; a second Python service competes with FastAPI + consumer. SDK Router lives inside the API. |
| **Policy** | `num_retries=0` by default; ≤1 configured fallback hop; paid markers fail closed. |
| **Evidence** | ADR 0002, `providers/router_factory.py`, `test_router_factory.py`, `test_model_client.py`. |

### Provider aliases & capability mapping — IMPLEMENTED (capability live matrix PARTIAL)

Aliases: `rm-planner`, `rm-researcher`, `rm-verifier`, `rm-writer`, `rm-eval-judge`. Tool-calling / structured-output per provider remain **unverified** for all allowlisted models; graph uses JSON text parse instead of requiring JSON mode (ADR 0003).

### Token budgets — IMPLEMENTED (server-side caps)

`MAX_MODEL_CALLS_PER_RUN`, `MAX_RUN_WALL_CLOCK_SECONDS`, graph `max_model_calls=12`. Estimated USD cost is a **list-price** string when tokens/search are measured (`backend/app/cost_estimate.py`); stays **null**/UI unknown when unmeasured — never coerced to fake zero.

---

## Research infrastructure

| Technology | Status | Notes |
|---|---|---|
| Multi-query planning ≤3 | IMPLEMENTED · VERIFIED | Planner node + clamp |
| Tavily search | IMPLEMENTED · VERIFIED (offline mocks) | Client in `research/retrieval.py`; V2 caps results at 3 (V1 used 5) |
| Multi-source extract ≤6 | IMPLEMENTED · VERIFIED | vs V1’s one reader scrape |
| Structured evidence passages | IMPLEMENTED · VERIFIED | `research/evidence.py` |
| Claim verification (passage overlap) | IMPLEMENTED · VERIFIED | “evidence assessed,” not absolute fact-check |
| Contradiction detection | IMPLEMENTED · VERIFIED | graph tests cover contradictions |
| PDF extraction | DEFERRED | `pdf_enabled=False` |
| Hybrid BM25 / embeddings / RRF / pgvector | DEFERRED | Not needed for per-run evidence store |

---

## Evaluation

### DeepEval — PARTIALLY IMPLEMENTED

Selected as primary LLM-app eval framework (SoT). Pin `deepeval==4.3.3` in `evals/requirements.txt` only — the judge is **not** installed in CI or the backend venv. Judge gated by `RM_EVAL_JUDGE=1` + `--confirm-offline`. Judge scores exist only for hand-built fixtures (2026-11-09, Meta Muse); V1/V2 scores **NOT MEASURED**. RAGAS explicitly not primary.

Deterministic Python checks for fixtures: IMPLEMENTED · VERIFIED (`evals/checks.py`, 15 eval unit tests; CI runs them plus the deterministic self-check).

---

## Observability

OpenTelemetry spans + redaction: PARTIALLY IMPLEMENTED · VERIFIED offline. Default/`render.yaml` sets `OTEL_TRACES_EXPORTER=none`. Paid APM not required.

---

## External integration (MCP)

Cloudflare Worker + Streamable HTTP-style MCP surface: IMPLEMENTED · VERIFIED · deployed. OAuth resource server: PLANNED (ADR 0006). Worker does not run LangGraph.

---

## Frontend

| Choice | Status | Why |
|---|---|---|
| React + TypeScript + Vite | IMPLEMENTED · VERIFIED | SPA screens, typed client, Vite proxy |
| Local UI primitives + plain CSS (Tailwind removed 2026-11-10) | IMPLEMENTED | Lightweight; not a full shadcn codegen tree |
| SSE via `@microsoft/fetch-event-source` | IMPLEMENTED · VERIFIED | Bearer headers (EventSource cannot set them) |
| Streamlit as V2 UI | REJECTED | Kept only as V1 baseline |

---

## Deployment

| Choice | Status | Why |
|---|---|---|
| Render Free Docker API (Singapore) | IMPLEMENTED (live) | Python Docker, public URL, student cost |
| Neon Free (Singapore) | IMPLEMENTED (live) | Durable Postgres without 30-day Render free DB expiry |
| Vercel Hobby console (`sin1`) | IMPLEMENTED (live) | Static SPA |
| Cloudflare Workers Free MCP | IMPLEMENTED (live) | Thin forwarder; 100k req/day, 10 ms CPU ([CF limits](https://developers.cloudflare.com/workers/platform/limits/), verified 2026-11-08) |
| Docker | IMPLEMENTED | Portable API image (built in CI, no push); `WEB_CONCURRENCY=1` enforced |

### Platform alternatives considered

| Platform | Verdict |
|---|---|
| Railway / Fly.io | Capable; not selected for the first student profile after SoT chose Render+Neon+Vercel+CF. Revisit only with measured Render Free failure. |
| Streamlit Cloud for V2 | Rejected — V2 is FastAPI/React. |
| Paid Redis / separate worker | Deferred until concurrency metrics justify cost. |

---

## Trade-off summary

ResearchMind 2.0 optimizes for **demo honesty under free tiers**: one process, durable Postgres, free-only models, SSE replay, and thin MCP. It deliberately under-optimizes for HA, exactly-once LLM billing, closed SSRF, and always-on compute. Those are documented risks, not silent omissions.
