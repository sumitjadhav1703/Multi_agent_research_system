# Resume and portfolio evidence

**Purpose:** map claims to files, tests, and measured results. Unsupported wins stay **pending validation**.

**Safe one-liner:**  
ResearchMind 2.0 is a FastAPI + LangGraph + LiteLLM free-tier research demo with Neon-backed jobs/quotas, SSE progress, a React console, and a thin Cloudflare MCP Worker; offline suites and deterministic eval fixtures are green; Singapore public URLs are documented; LLM-judge quality scores and cold-start metrics were not measured.

---

## Claim ledger

| Resume-oriented claim | Support files | Tests | Benchmark / measure | Status |
|---|---|---|---|---|
| Built multi-agent research orchestration with LangGraph bounds | `backend/app/graph/*`, ADR 0003 | `test_graph_workflow.py` | Latency NOT MEASURED | **Supported (functional)** |
| Parallel research workers capped at 2 via `Send` | `graph/builder.py`, `limits.py` | worker-wave tests | Speedup NOT MEASURED | **Supported (functional)** |
| Multi-provider routing with free-only allowlist | `providers/*`, `config.py`, ADR 0002 | router + model client tests | Live matrix partial | **Supported (functional); live partial** |
| Provider failover without paid escape | fallbacks in router_factory; fail-closed paid | config tests | Fallback frequency NOT MEASURED | **Supported (policy + tests)** |
| Evidence-grounded reports with citation checks | `research/evidence.py` | `test_citations.py` | Live citation precision NOT MEASURED | **Supported (functional)** |
| Claim-level verification / polarity | evidence + graph verify; Codex P2 | graph + citation tests | Quality delta NOT MEASURED | **Supported (functional)** |
| DeepEval evaluation harness | `evals/judge.py`, pin 4.3.3 | eval unit 14 OK; dry-run | Judge scores NOT MEASURED | **Harness only — do not claim scored gains** |
| SSE live progress with replay | `api/v1/stream.py`, frontend sse | `test_sse_stream.py` | Hosted SSE NOT MEASURED | **Supported (functional)** |
| PostgreSQL job leases + checkpoint resume | `jobs/lease.py`, checkpointer, migration | `test_postgres_durability.py` | Neon-specific NOT MEASURED | **Supported locally** |
| One-use guest quotas + Turnstile | `jobs/quota.py`, turnstile | `test_jobs_quota.py` | Abuse rate NOT MEASURED | **Supported (functional)** |
| Prompt-injection fixtures / fixed tools | graph tests, retrieval ports | injection cases in graph tests | Residual risk acknowledged | **Partial — not “solved injection”** |
| Public Render/Vercel/Neon/CF deploy (Singapore) | deployment-report, render.yaml, vercel.json | health checks documented | Cold-start NOT MEASURED | **Supported (URLs documented)** |
| Cost optimization via free tiers + budgets | GraphLimits, settings caps | zero-budget / quota tests | $ saved NOT MEASURED | **Supported (design); no $ claim** |
| Replaced Streamlit with React research console | `frontend/**` | 16 vitest + build | UX study NOT MEASURED | **Supported (shipped UI)** |
| Remote MCP tool access | `mcp-server/**` | 29 vitest | Inspector E2E NOT RECORDED | **Supported (deployed forwarder)** |

---

## Phrases to avoid until measured

- “X% faster research”  
- “Y% cheaper inference”  
- “Production-ready / enterprise-grade security”  
- “SSRF fully mitigated”  
- “Exactly-once LLM execution”  
- “DeepEval shows superior quality vs V1”  
- “Handles N concurrent users” without cap honesty (`GLOBAL_MAX_ACTIVE_RUNS`)

---

## Suggested bullet templates (edit numbers only after evidence)

1. Engineered a bounded LangGraph research workflow (≤3 subquestions, ≤2 workers, evidence ledger, human review interrupt) with offline unit coverage.  
2. Implemented LiteLLM SDK Router role aliases with a fail-closed free-model allowlist and no paid fallback.  
3. Built Neon-backed job leases, idempotent starts, and one-use guest quotas enforced in PostgreSQL—not the browser.  
4. Shipped a React + SSE Research Console and a Cloudflare Worker MCP forwarder against a Singapore Render API.  
5. Authored an offline DeepEval/deterministic eval harness (32 golden questions); scored V1/V2 comparison pending.

---

## Portfolio review checklist

- [ ] Link engineering-story README  
- [ ] Link live console + API health  
- [ ] Show V1 vs V2 architecture diagrams (implemented vs planned colors)  
- [ ] Paste only test counts and dates from IMPLEMENTATION_STATUS / RESULTS  
- [ ] Call out open SSRF and unmeasured judge scores verbally in interviews  

Honesty is part of the engineering story.
