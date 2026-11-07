# Optimization and experiments register

**Rule:** no experiment is “successful” without measured results. Most entries are **PLANNED** or **RUNNING (code shipped, metrics pending)**.

---

## Register

| ID | Hypothesis | Baseline | Change | Test method | Result | Trade-off | Decision | Status |
|---|---|---|---|---|---|---|---|---|
| E01 | Parallel ≤2 workers cut wall-clock vs sequential V1 | V1 sequential (latency NOT MEASURED) | LangGraph Send ≤2 | Same questions; mock + live | NOT MEASURED | More RPM pressure | Keep bound=2 until measured | Code **IMPLEMENTED**; result pending |
| E02 | Higher concurrency (>2) helps | Bound=2 | Raise to 3–4 | Ablation on Free tier | NOT RUN | Throttle/OOM risk | Do not raise yet | PLANNED |
| E03 | More search hits improve recall | V1 max_results=5; V2 ≤3×queries | Vary K | Labeled Precision/Recall | NOT MEASURED | Tavily quota | Hold ceilings | PLANNED |
| E04 | Multi-source ≤6 beats one reader scrape | V1 one scrape | Evidence ledger | Citation precision fixtures + judge later | Fixtures only; quality NOT MEASURED | Fetch cost | Keep | IMPLEMENTED / unmeasured quality |
| E05 | PDF parsing improves academic topics | Snippet-only PDFs | Enable parser | Subset of PDF-heavy questions | NOT RUN | CPU/RAM | Deferred | DEFERRED |
| E06 | URL+hash dedupe lowers duplicates | No merge dedupe | Merge node | Duplicate ratio | NOT MEASURED | — | Keep | IMPLEMENTED |
| E07 | Passage grounding reduces invented cites | V1 writer free-form | claim_grounded + validate_citations | Deterministic tests | Unit tests PASS; live rate NOT MEASURED | May mark insufficient | Keep | IMPLEMENTED |
| E08 | Claim verification improves faithfulness | Critic-only V1 | Verify node | DeepEval faithfulness | NOT MEASURED | Extra tokens | Keep code; measure offline | PENDING |
| E09 | Free multi-provider failover raises completion | Single Groq V1 | LiteLLM allowlist fallbacks | Failure/completion rates | Partial live smoke only | Complexity | Keep free-only | PARTIAL |
| E10 | Zero router retries reduce double-bill | SDK retries >0 | num_retries=0 | Timeout injection tests | Design rationale; cost NOT MEASURED | Less resilience | Keep | IMPLEMENTED |
| E11 | SSE beats polling for UX | Streamlit status | SSE + replay | Qualitative + reconnect tests | Unit VERIFIED; hosted NOT MEASURED | Connection handling | Keep | IMPLEMENTED |
| E12 | Postgres leases survive restart | Session state V1 | SKIP LOCKED + checkpoints | Local durability tests | Local VERIFIED; Neon NOT MEASURED | At-least-once LLM | Keep | IMPLEMENTED |
| E13 | Caching cuts repeat cost | None | Response cache | Repeat topics | NOT RUN | Stale web | Investigate only if measured waste | PLANNED |
| E14 | Prompt shortening cuts tokens | Current prompts | Ablation | Token ledger | NOT MEASURED | Quality risk | Pending | PLANNED |
| E15 | Token budgets stop runaway jobs | Unlimited V1 starts | Wall clock + max calls | Zero-budget tests (Codex P2) | Unit VERIFIED | Hard stops | Keep | IMPLEMENTED |
| E16 | DeepEval config stability | N/A | Pin 4.3.3 + temp 0 | Dry-run + future scored run | Dry-run constructs metrics; scores null | Judge cost | Keep pin | PARTIAL |

---

## How to close an experiment

1. Write hypothesis + commit SHA.  
2. Freeze dataset slice.  
3. Run N≥5 with recorded env.  
4. Store raw outputs under gitignored `evals/results/`.  
5. Update this table’s Result + Decision.  
6. Never backfill invented percentages.

---

## Priority order for first real measurements

1. E12 hosted restart recovery on Neon/Render  
2. E01 warm-path wall-clock V1 vs V2 (small N)  
3. E07/E08 citation + faithfulness offline judge on frozen fixtures  
4. Cold-start (infra) recorded in deployment-report  
