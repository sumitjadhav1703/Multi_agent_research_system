# ResearchMind 2.0 — Bug inventory

**Updated:** 2026-11-09 (fix wave applied)  
**Models this fix wave:** Parent Cursor Auto/Composer; frontend-implementer Grok 4.7 (Sonnet 5 weekly usage exhausted). Not Opus / Sonnet 5.

## Fix-wave verification

Command: `RUN_NODE_SUITES=1 bash scripts/run_offline_suites.sh` (exit 0).

| Suite | Result |
| --- | --- |
| V1 | Ran 16 — OK |
| V2 backend | Ran 154 — OK (skipped=1) |
| evals unit | Ran 14 — OK |
| deterministic eval | 20 runs, 0 fixture mismatches |
| frontend | lint/typecheck/build OK; Vitest includes promoted discovery tests |
| mcp-server | Vitest OK |

Discovery tests for fixed IDs are **hard gates** (no longer `@unittest.expectedFailure` / `it.fails`).

Live bounded smoke after fixes: `/health/live` and `/health/ready` re-checked (no Turnstile consume; no deploy of this fix wave yet).

---

## P1 code

| ID | Status | Fix |
| --- | --- | --- |
| BI-P1-1 | **fixed** | Removed post-`start` wall-clock overwrite in [`executor.py`](../backend/app/jobs/executor.py). |
| BI-P1-2 | **fixed** | Stable [`number_events`](../backend/app/graph/events.py); awaiting uses `max_id+1`; persist dedupes `(event_id, type)`. |
| BI-P1-3 | **fixed** | SSE retries 502/503 and `unavailable`; terminals include `rejected` ([`sse.ts`](../frontend/src/api/sse.ts)). |
| BI-P1-4 | **fixed** | Retention selects only `TERMINAL_STATUSES` ([`retention.py`](../backend/app/jobs/retention.py)). |
| BI-P1-5 | **fixed** | `ACTIVE_STATUSES = ("queued", "running")` ([`quota.py`](../backend/app/jobs/quota.py)). |

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

13 nodes remain fully connected. No topology change in this wave.
