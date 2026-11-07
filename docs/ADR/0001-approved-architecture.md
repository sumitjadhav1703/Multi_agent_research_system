# ADR 0001 — Approved ResearchMind 2.0 Architecture

- **Status:** Accepted (product/architecture); implementation not started  
- **Date:** 2026-11-07  
- **Deciders:** Project owner (approved source-of-truth plan); Gate 0 audit records acceptance into this repository  
- **Canonical spec:** [`docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md`](../RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md)  
- **Execution status:** [`docs/IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md)

---

## Context

The live repository at commit `f1881b9` is **ResearchMind V1**: a Streamlit + LangChain/Groq sequential pipeline (Search → Read → Write → Critic) with Tavily search, bounded HTML scrape, in-memory resume, mocked offline tests, and a Streamlit Community Cloud deploy.

The approved V2 blueprint requires a production-style student demo with durable jobs, multi-provider routing, evidence-linked research, React UI, evaluation, remote MCP, and public deployability — without claiming production SLAs or inventing metrics.

Gate 0 confirmed: **no application V2 implementation exists yet**. Kit documents and Cursor agents were copied into the repo for orchestration; V1 source remains intact.

---

## Decision

Adopt the architecture in `docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md` without simplifying away required components:

1. **Preserve V1** as baseline (Streamlit path remains runnable) until V2 milestones pass their gates.  
2. **Backend:** FastAPI + LangGraph (max two parallel research workers) + LiteLLM **SDK Router** (no separate Proxy until measured need).  
3. **Persistence:** Neon PostgreSQL for jobs, events, quotas/idempotency, evidence, and LangGraph checkpoints (`langgraph-checkpoint-postgres` / `AsyncPostgresSaver`).  
4. **Execution model:** One Render Web Service, `WEB_CONCURRENCY=1`, one bounded Postgres queue consumer in FastAPI lifespan (`FOR UPDATE SKIP LOCKED`); no FastAPI `BackgroundTasks` as durable work; no Redis/pgvector in v1 of V2.  
5. **Quotas:** Atomic one-run per account/issued guest identity; global concurrency/daily caps; per-run budgets; no paid provider fallback.  
6. **Frontend:** React + TypeScript + Vite Research Console; REST commands + fetch-based SSE with replay; no WebSockets/webhooks in first release.  
7. **Evaluation:** DeepEval for controlled benchmarks only, paired with deterministic citation/SSRF/quota checks.  
8. **MCP:** Thin authenticated Cloudflare Worker (Streamable HTTP) forwarding to FastAPI; no duplicated graph logic.  
9. **Deploy topology:** Render (API) + Neon + Vercel or Render Static (SPA) + Cloudflare (MCP). Public URL is definition-of-done.  
10. **Honesty:** No claims of exactly-once LLM execution or “production-ready”; document limits.

---

## Consequences

### Positive

- Clear milestone sequence and non-negotiable stack choices for subagents.  
- V1 remains a measurable baseline and fallback UX.  
- Security/cost controls are designed before public V2 traffic.

### Negative / costs

- Larger delivery surface than polishing Streamlit alone.  
- Free-tier provider and hosting limits will constrain concurrency and may require documented partial failures.  
- Parent must enforce file ownership and ≤2 write subagents to avoid integration thrash.

### Follow-on ADRs (planned, not written yet)

- `0002-provider-routing.md` — after capability tests pin free model IDs  
- `0003-queue-and-persistence.md` — lease/checkpoint details at M3  
- `0004-streaming-transport.md` — SSE event schema at M4  
- `0005-hosting-and-deployment.md` — measured Render/Neon/Vercel choices at M7  

---

## Gate 0 compliance note

This ADR records **architecture acceptance**, not milestone completion. Implementation remains blocked until Gate 0 model-role verification passes and the user reviews the audit package (`IMPLEMENTATION_STATUS.md`, `BASELINE_REPORT.md`, `RISK_REGISTER.md`).
