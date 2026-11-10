# Benchmarking and performance methodology

**Rule:** record actual numbers only. Until measured, status is **NOT MEASURED**.

**Environments of interest:**

| Env | Role |
|---|---|
| Local Python 3.13 + mock provider | Offline functional |
| Local throwaway Postgres | SKIP LOCKED / checkpoint |
| Render Free singapore + Neon ap-southeast-1 | Hosted demo |
| V1 Streamlit path | Baseline comparison |

---

## Reproducibility checklist

For every benchmark row eventually filled:

- Date (Asia/Calcutta or explicit offset)  
- Git commit SHA  
- Hardware / host plan (e.g., Render Free 0.1 CPU / 512 MB)  
- Model IDs + provider  
- `USE_MOCK_PROVIDER`  
- Dataset version / question ids  
- Number of runs  
- Measurement method (wall clock, server timestamps, browser)  
- Limitations (cold start included? search live?)  

Keep questions, source snapshots, and model configs constant across V1 vs V2 comparisons.

---

## Metric catalog

### Retrieval

| Metric | How to measure | Status |
|---|---|---|
| Search latency | Server timestamps around Tavily | NOT MEASURED |
| Relevant sources count | Human labels @K | NOT MEASURED |
| Duplicate source ratio | Canonical URL collisions / total | NOT MEASURED |
| Extraction success | fetch_status ok / attempted | NOT MEASURED (live) |
| Precision / Recall / MRR / NDCG | Labeled set | NOT MEASURED |

### Agent execution

| Metric | Status |
|---|---|
| Planner / worker / verify / write latency | NOT MEASURED |
| Parallel vs sequential wall time | NOT MEASURED |
| Tool-call count / iterations | Instrumentable from events; NOT MEASURED aggregate |
| Verification time | NOT MEASURED |

### Model infrastructure

| Metric | Status |
|---|---|
| Provider latency | NOT MEASURED |
| Fallback frequency | NOT MEASURED (logs possible) |
| Token in/out | Ledger fields; hosted aggregate NOT MEASURED |
| Estimated cost USD | List-price when tokens/search measured; null/unknown otherwise |
| Provider failure rate | NOT MEASURED |

### Complete workflow

| Metric | Status |
|---|---|
| Total research duration | NOT MEASURED |
| p50 / p95 | NOT MEASURED |
| Completion rate | NOT MEASURED |
| Partial-result recovery | VERIFIED in unit tests; hosted NOT MEASURED |
| API request count per run | NOT MEASURED |

### Infrastructure

| Metric | Status |
|---|---|
| Memory / CPU on Render | NOT MEASURED |
| Worker concurrency effectiveness | Bound=2; NOT MEASURED |
| DB query latency (Neon) | NOT MEASURED |
| SSE reconnect behavior hosted | NOT MEASURED |
| Cold start | Official ~1 min after 15 min idle; **local measurement NOT MEASURED** |

---

## Comparison matrix (to fill later)

| System | Description | Quality | Latency | Cost | Status |
|---|---|---|---|---|---|
| V1 four-stage | Sequential Streamlit | NOT MEASURED | NOT MEASURED | NOT MEASURED | Baseline code frozen |
| Multi-source V2 | ≤6 sources | NOT MEASURED | NOT MEASURED | NOT MEASURED | Code IMPLEMENTED |
| Parallel V2 | ≤2 workers | NOT MEASURED | NOT MEASURED | NOT MEASURED | Code IMPLEMENTED |
| Evidence-verified V2 | Claims + citations | NOT MEASURED | NOT MEASURED | NOT MEASURED | Code IMPLEMENTED |

---

## Offline performance signals (not latency benchmarks)

| Signal | Evidence |
|---|---|
| V1 unittest | 16 tests (CI `v1` job) |
| V2 backend unittest | 224 tests, mock provider (CI `backend` job) |
| Frontend vitest | 47 tests + production build (CI `frontend` job) |
| MCP vitest | 31 tests (CI `mcp` job) |
| Eval unit tests | 15 tests (CI `evals` job) |
| Eval fixtures | 32/20 deterministic self-check |

These prove **engineering test speed under mocks**, not research wall-clock on free LLMs.

---

## Suggested first measurement protocol (do not invent results)

1. Warm the Render service with `/api/v1/health/live`.  
2. Issue guest identity; start one short topic with mock or tiny live budget.  
3. Record timestamps: 202 response, first SSE event, terminal event.  
4. Repeat 5× cold and 5× warm; report median and p95 separately.  
5. Export usage_ledger tokens if present; list-price cost when measurable, else leave cost null/unknown.  
6. Write results into `docs/evals/` or append this file with commit SHA — never overwrite with guesses.
