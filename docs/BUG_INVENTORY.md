# ResearchMind 2.0 — Bug inventory

**Updated:** 2026-11-10 (post-merge delta)  
**Models this delta:** Parent Cursor Auto/Composer; explore agents for graph/frontend. Not Opus / Sonnet 5.

## Post-merge delta verification (2026-11-10)

Scope: re-verify fix wave + LangGraph connectivity + new upstream provisional/passage/Meta/eval paths only. Residuals unchanged unless worse.

Command: `RUN_NODE_SUITES=1 bash scripts/run_offline_suites.sh` (exit 0).

| Suite | Result |
| --- | --- |
| V1 | Ran 16 — OK |
| V2 backend | Ran 179 — OK (skipped=1) |
| evals unit | Ran 14 — OK |
| frontend | Test Files 10 / Tests 36 — OK |
| mcp-server | Test Files 3 / Tests 29 — OK |

Hard gates: `test_bug_discovery_p1` + `p2` + `test_graph_workflow` (25) OK; frontend `*.discovery.test.ts` (3) OK.

Live smoke (no Turnstile): API live/ready 200; console `/` and `/app` 200; MCP unauth 401.

**Graph:** nodes/edges/routers still connected after provisional/passage changes; no new orphan or dead-end; human review / fail / `Send("worker")` paths intact. No new graph P0/P1.

**New P0/P1 from delta:** BI-P1-20 only (eval chart honesty). No crash, broken edge, empty-answer, or auth/quota bypass found on provisional/passage/Meta paths.

**Delta P2 / low (recorded, not fixed):** Report empty-copy polish; score rounding display elsewhere. Residuals BI-P2-7/8/16/18/19, R04/R10/R12, BI-P1-6 still open.

---

## Fix-wave verification (historical, 2026-11-09)

Prior matrix: V1 16; backend 154; evals 14; discovery promoted to hard gates. See git history for that wave.

---

## P1 code

| ID | Status | Fix |
| --- | --- | --- |
| BI-P1-1 | **fixed** | Removed post-`start` wall-clock overwrite in [`executor.py`](../backend/app/jobs/executor.py). |
| BI-P1-2 | **fixed** | Stable [`number_events`](../backend/app/graph/events.py); awaiting uses `max_id+1`; persist dedupes `(event_id, type)`. |
| BI-P1-3 | **fixed** | SSE retries 502/503 and `unavailable`; terminals include `rejected` ([`sse.ts`](../frontend/src/api/sse.ts)). |
| BI-P1-4 | **fixed** | Retention selects only `TERMINAL_STATUSES` ([`retention.py`](../backend/app/jobs/retention.py)). |
| BI-P1-5 | **fixed** | `ACTIVE_STATUSES = ("queued", "running")` ([`quota.py`](../backend/app/jobs/quota.py)). |
| BI-P1-20 | **fixed** | Evaluation chart: judge 0–1 means labeled `mean score (0–1)` with decimal Y-axis; deterministic keeps `fixture runs`. Snapshot strip shows real `error_count` / skipped. Regression: [`EvaluationPage.discovery.test.tsx`](../frontend/src/pages/EvaluationPage.discovery.test.tsx). |

## P1 ops

| ID | Status | Notes |
| --- | --- | --- |
| BI-P1-6 | **ops** | Provider/Gemini availability. Not a code fix. |

## P2 code

| ID | Status | Fix / note |
| --- | --- | --- |
| BI-P2-7 | **residual** | `retryable` still unused; left for a lease/retry design pass. |
| BI-P2-8 | **residual** | Lost-lease race (R09); needs abort-on-heartbeat-loss design. |
| BI-P2-9 | **fixed** | Failed search sets `search_calls=1` ([`evidence.py`](../backend/app/research/evidence.py)). |
| BI-P2-10 | **fixed** | Reject → job status `rejected` (terminal). |
| BI-P2-11 | **fixed** | `clearToken` also clears `CURRENT_RUN_KEY`. |
| BI-P2-12 | **fixed** | Failed banner shows `stop_reason` when `error_code` empty. |
| BI-P2-13 | **fixed** | Turnstile reset on failure / expired / error. |
| BI-P2-14 | **fixed** | Idempotency key kept while start is pending. |
| BI-P2-15 | **fixed** | `untrusted_block` neutralizes inner delimiters. |
| BI-P2-16 | **residual** | `--forwarded-allow-ips='*'` needs Render peer allowlist. |
| BI-P2-17 | **fixed** | MCP `wrangler.jsonc` defaults to Singapore API. |
| BI-P2-18 | **residual** | Ready ignores dead consumer; sync SSE poll. |
| BI-P2-19 | **residual** | Free allowlist is name markers, not a price oracle. |

## Known residuals (still open)

- **R04** SSRF: in-process IP dial only; no egress proxy.
- **R10** Render Free sleep / long SSE.
- **R12** Neon pooler vs LangGraph checkpointer unmeasured.
- MCP OAuth deferred (ADR 0006).
- CI skips Postgres `SKIP LOCKED` when local Postgres tools missing.

## Graph

13 nodes remain fully connected. Post-merge delta re-verified builders/routers after provisional/passage upstream; still no orphan or dead-end.
