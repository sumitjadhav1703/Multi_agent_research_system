# ResearchMind 2.0 — Bug inventory

**Updated:** 2026-11-10 (wipe-ready handoff)  
**Models this delta:** Parent Cursor Auto/Composer; explore agents for graph/frontend. Not Opus / Sonnet 5.

## Post-delta ships (2026-11-10, after inventory)

| Item | Status | Note |
| --- | --- | --- |
| Live drawer horizontal overflow | **fixed** | CSS `min-width: 0` + wrap + fixed drawer track |
| Report Export Markdown / Print | **fixed** | Blob `.md` of answer body; print CSS hides chrome, unclamps preview |
| List-price estimated cost | **fixed** | `backend/app/cost_estimate.py` + ledger/`/me/usage`/Usage UI |
| CI/Vercel `ReportPage.test.ts` tsc | **fixed** | `793f792` |
| Stale `cursor/fix-empty-report-answer-8a03` | **deleted** | Already on main via PR #14/#15 |

Residuals below unchanged.

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

**Delta P2 / low (recorded, not fixed):** Report empty-copy polish; score rounding display elsewhere. Residuals BI-P2-7/8/16/18/19 (7, 8 and part of 18 since fixed; see 2026-11-10 audit), R04/R10/R12, BI-P1-6 still open.

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
| BI-P2-7 | **fixed** | Dead retry path removed from `persist.py` (fixed 2026-11-10 on fix/audit-hardening). |
| BI-P2-8 | **fixed** | Lost lease now stops the graph early (fixed 2026-11-10 on fix/audit-hardening). Postgres lease SQL still untested in CI (R09 at-least-once stays). |
| BI-P2-9 | **fixed** | Failed search sets `search_calls=1` ([`evidence.py`](../backend/app/research/evidence.py)). |
| BI-P2-10 | **fixed** | Reject → job status `rejected` (terminal). |
| BI-P2-11 | **fixed** | `clearToken` also clears `CURRENT_RUN_KEY`. |
| BI-P2-12 | **fixed** | Failed banner shows `stop_reason` when `error_code` empty. |
| BI-P2-13 | **fixed** | Turnstile reset on failure / expired / error. |
| BI-P2-14 | **fixed** | Idempotency key kept while start is pending. |
| BI-P2-15 | **fixed** | `untrusted_block` neutralizes inner delimiters. |
| BI-P2-16 | **residual** | `--forwarded-allow-ips='*'` needs Render peer allowlist. |
| BI-P2-17 | **fixed** | MCP `wrangler.jsonc` defaults to Singapore API. |
| BI-P2-18 | **partial** | SSE poll fixed 2026-11-10 on fix/audit-hardening (off event loop, snapshot only on change, 15 min cap, closes on terminal). Ready ignoring a dead consumer is still open. |
| BI-P2-19 | **residual** | Free allowlist is name markers, not a price oracle. |

## 2026-11-11 live answers were snippets, not claims (fix/relevant-passages)

Found in a live run after the audit merge: every claim stayed `insufficient`, and the report showed raw page snippets. Each cause was confirmed with recorded live model output.

| Cause | Fix |
| --- | --- |
| Passages came from the first 2000 chars of each page, which on real sites is menus ("Skip to content…"). The extractor correctly found no claims. | Excerpt now leads with the search snippet (relevant text from the same page), then page text, still capped at 2000 chars. Test: `PageHeadBoilerplateTests`. |
| `groq/openai/gpt-oss-20b` reasons before answering. On extraction it spent 798 of 800 `max_tokens` thinking and returned empty content (`finish=length`). | One 2000-token completion budget (`MAX_COMPLETION_TOKENS` in `graph/nodes.py`) for all four roles. |
| Verifier primary Gemini returned 503/timeouts and fallback Mistral returned 429, so no claim could be verified. | Verifier fallback default is now `groq/openai/gpt-oss-20b`. Render's dashboard value must be changed too. |

Live check after all three: 12 claims extracted, 12 supported, no warnings.

Follow-up the same day: Gemini and Mistral were removed from every default, `render.yaml` and the allowlist. The roles now run on:
- Groq `gpt-oss-120b` and `gpt-oss-20b`.
- OpenRouter Nemotron as the verifier.
- OpenRouter Nemotron as the fallback (NVIDIA NIM is supported but failed live probes, so it is not a default).
- Meta Muse as the enabled paid last resort.

See `docs/engineering-story/provider-routing-and-failover.md`.

### 2026-11-12 follow-up (fix/extract-relevance)
- The extractor prompt never included the research question, so live claims included page metadata ("The article has 25 pages"). The question is now in the prompt, and the extractor is told to skip metadata.
- In about 1 in 10 live runs the model returned a valid `{"claims":[]}` for passages that gave claims on the next call. Extraction now retries once when no usable claims come back.
- The fallback warning now records `proposed=N kept=0`.
- Two full local API runs (guest → review → approve) both completed, with 7 and 4 supported claims.

## 2026-11-10 audit (fix/audit-hardening)

Findings below were fixed 2026-11-10 on fix/audit-hardening. Suites after the fix: V1 16, backend 224, evals 15, frontend 47, MCP 31.

| Finding | Status |
| --- | --- |
| P1 stuck queued job held the only slot (review resume kept attempts; cancel/review raced) | **fixed** (conditional UPDATEs, attempts reset, periodic recovery) |
| P1 no DB-init retry after Neon failure | **fixed** (background retry, 5s backoff to 60s) |
| P1 follow-up evidence never read by extractor/writer | **fixed** (round-robin passage pick) |
| P2 retry without a free source slot / refetch of known URLs | **fixed** |
| P2 empty provider content had no fallback | **fixed** (role fallback model) |
| P2 Meta last resort auto-enabled by key alone | **fixed** (needs `META_LAST_RESORT_ENABLED=true` + key + allowlisted model) |
| P2 wall-clock deadline unenforced | **fixed** (checked between steps; `expired` / `wall_clock`) |
| P2 duplicate `run.*` status events | **fixed** |
| P2 SSE poll blocked the event loop | **fixed** (see BI-P2-18) |
| P2 identity DB error returned 500 without CORS | **fixed** (503 with CORS) |
| P2 Neon never idle (queue polling) | **fixed** (wake signal; `QUEUE_IDLE_POLL_SECONDS=300`) |
| P2 GitHub keep-awake cron throttled | **fixed** (Worker cron `*/10`; GitHub workflow manual only) |

Also fixed: revise at the revision limit returns to review with a warning; token counting continues after a failed call; Turnstile `remoteip` dropped and siteverify hostname checked (not BI-P2-16, which is the forwarded-allow-ips item); migration 0002 index cleanup; `/health/ready` trimmed to status, database, `use_mock_provider`.

## Known residuals (still open)

- **R04** SSRF: in-process IP dial only; no egress proxy. Fetch now lives in `backend/app/research/fetch.py` with an overall read deadline; still not closed.
- **R10** Render Free sleep / long SSE (Worker cron keep-alive reduces it; not an SLA).
- **R12** Neon pooler vs LangGraph checkpointer unmeasured.
- MCP OAuth deferred (ADR 0006).
- `elapsed_ms` not persisted across a review resume.
- OTel setup couples to a private field.
- Lighter MCP report queries skipped.
- Postgres-only lease SQL (`SKIP LOCKED`) untested in CI.

## Graph

13 nodes remain fully connected. Post-merge delta re-verified builders/routers after provisional/passage upstream; still no orphan or dead-end.
