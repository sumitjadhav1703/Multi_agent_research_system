# ResearchMind 2.0 — Implementation Status

**Updated:** 2026-11-08  
**Repository root:** `/workspace`  
**Git:** feature branch for data retention (see latest commit)  
**Current gate:** **Singapore public stack + MCP Worker are live.** Neon `aws-ap-southeast-1`, Render `singapore` API, Vercel console `sin1`, MCP `https://researchmind-mcp.jadhavsumit534.workers.dev`. Oregon deleted. CORS OK. Turnstile + provider keys are configured on the hosts; live ready reports `use_mock_provider: false`.

### Follow-up: 2-day data retention (this change)

- **IMPLEMENTED:** `backend/app/jobs/retention.py` purges research jobs older than `DATA_RETENTION_DAYS` (default **2**) plus orphan guest identities. Runs on lifespan startup and periodically inside `QueueConsumer` (`DATA_RETENTION_INTERVAL_SECONDS`, default 3600).  
- **Does not delete** `quota_guard`. Postgres LangGraph checkpoint cleanup is best-effort by `thread_id`.  
- **Env:** `DATA_RETENTION_ENABLED`, `DATA_RETENTION_DAYS`, `DATA_RETENTION_INTERVAL_SECONDS`, `DATA_RETENTION_BATCH_SIZE` (also set in `render.yaml` / `.env.example`).  
- **Tests:** `backend/tests/test_retention.py`. Full backend offline suite on this change: **108 tests, 2 skipped (local Postgres durability), OK** (`USE_MOCK_PROVIDER=true`, Python 3.12 venv).  
- **Not claimed:** hosted Neon purge metrics; automatic vacuum/storage reclaim timing on Neon. After merge, set the new env vars on Render (or redeploy from `render.yaml` values) so production starts purging.

---

## Model attribution (honest)

| Role | Required | Actual this session |
|---|---|---|
| Parent orchestrator | Claude Opus 5.5 High | Cursor Auto/Composer (user-executed plan after Gate 0) |
| backend-implementer | Claude Sonnet 5 | **Unavailable** (weekly usage). M0–M1 implemented by parent. **M2, M3, and the M3 security follow-up were implemented by Grok 4.7**, explicitly authorized because Sonnet 5 weekly usage was exhausted |
| frontend-implementer | Claude Sonnet 5 | **Unavailable.** **Milestone 4 was implemented by Grok 4.7**, explicitly authorized by the user. Not Sonnet 5. |
| test-engineer | Claude Sonnet 5 | **Unavailable.** **Milestone 5 evaluation half was implemented by Grok 4.7**, explicitly authorized by the user. Not Sonnet 5. |
| M5 observability | Claude Sonnet 5 | **Unavailable.** **Implemented by Grok 4.7**, explicitly authorized. Not Sonnet 5. |
| M6 remote MCP | Claude Sonnet 5 | **Unavailable.** **Implemented by Grok 4.7**, explicitly authorized. Not Sonnet 5. |
| M7 deployment artifacts | Claude Sonnet 5 | **Unavailable.** **Implemented by Grok 4.7**, explicitly authorized. Not Sonnet 5. |
| Scope | M0 through M7 artifacts | Public deploy was not performed |

Do not claim Opus 5.5 High or Sonnet 5 ran for M0, M1, M2, M3, the M3 security follow-up, M4, the M5 evaluation half, M5 observability, M6, or M7.

---

## Gate / milestone board

| Milestone | Status | Evidence |
|---|---|---|
| Gate 0 audit | Complete (prior) | Baseline docs present |
| M0 V1 freeze | **Pass** | Tag `v1-baseline`; V1 tests 13/13 OK; live metrics not measured |
| M1 LiteLLM + FastAPI foundation | **Code+tests complete** | Backend package + original 23 offline tests still OK; V1 still 13/13 |
| M2 LangGraph evidence graph | **Code+tests complete — awaiting parent review** | 47 backend tests at M2 handoff; still included in the M3 suite |  
| M3 PostgreSQL, jobs, quotas | **Code+tests complete — security follow-up applied** | Independent review PASS WITH CONDITIONS. Follow-up suite: backend 73/73 OK; V1 14/14 OK |  
| M4 React console and SSE | **Code+tests complete — awaiting parent review** | Frontend lint, typecheck, 16/16 unit tests, production build. Backend suite includes the new SSE tests. |
| M5 evaluation half | **Code+tests complete — awaiting parent review** | 32-question golden set. Deterministic fixture self-check 20/20. Eval unit tests 14/14 OK. Judge scores not measured. |
| M5 observability | **Code+tests complete — awaiting parent review** | Backend 85/85 OK in 2.129s, 0 skipped. DeepEval files were not edited. |
| M6 remote MCP | **Code+tests complete — awaiting parent review** | Worker 29/29. Backend 88/88 OK in 2.284s. Wrangler 4.158.0 dry-run only. Not deployed. |
| M7 deploy artifacts | **Artifacts written — not deployed** | Backend 95/95 OK in 2.293s. `render.yaml` schema 0 errors. No Docker image, no Render/Vercel/Neon/Worker URL. |

---

## Milestone 0

- **Tag:** `v1-baseline` → `f1881b91ac6b28e476c9ae7533dbae91ce26e3cf`
- **Command:** `/tmp/rm_v1_venv/bin/python -m unittest discover -s tests -v` → Ran 13, OK
- **Live provider baseline:** Not measured (no credentials exercised)

---

## Milestone 1

### Assigned task

Backend foundation: FastAPI package boundary, typed settings, LiteLLM SDK Router role aliases, free-only allowlist, mock provider, capability/failover unit tests. Preserve V1 Streamlit.

### Owned files (created/updated)

- `backend/app/main.py`
- `backend/app/core/config.py`
- `backend/app/providers/*` (client, router_factory, mock_router, errors, usage)
- `backend/app/api/v1/health.py`
- `backend/tests/*`
- `backend/requirements.in`, `backend/requirements.txt`
- `.env.example`
- `.github/workflows/tests.yml`
- `docs/ADR/0002-provider-routing.md`

### Decisions

- Package layout `backend/app/...` beside untouched V1 modules
- Mock router for CI; real LiteLLM Router only when `USE_MOCK_PROVIDER=false`
- Fail closed on `ALLOW_PAID_MODELS=true` and non-allowlisted / paid-marker models
- Prefer Python **3.13** for backend (3.15 fails LiteLLM native builds locally)

### Tests run

```text
# V2 backend (Python 3.13.14 venv)
USE_MOCK_PROVIDER=true PYTHONPATH=. python -m unittest discover -s backend/tests -v
Ran 23 tests in 0.119s — OK

# V1 regression
python -m unittest discover -s tests -v
Ran 13 tests in 0.694s — OK
```

**Pass counts:** backend 23/23, V1 13/13, total 36/36 offline.

### Migrations / env vars

No DB migrations (M3). New env vars documented in `.env.example` (allowlist, role models, mock flag, optional Gemini/Mistral/OpenRouter keys).

### Known limitations / unverified

- Live Groq/Gemini/Mistral tool-calling and structured-output capability **not** exercised against real APIs
- Default free model IDs are illustrative until capability matrix is measured
- LiteLLM Proxy not deployed (intentional)
- No research-run API, LangGraph, Postgres, React, MCP yet (later milestones)

### Parent review decision

**Provisional pass on offline acceptance criteria.** Live provider matrix remained open at the M1 handoff. M2 was assigned later the same day; the current gate is M2.

---

## Milestone 2

### Assigned task

Bounded LangGraph evidence-first research: planner (≤3), fan-out (≤2), V1-backed search/fetch, evidence ledger, claim verification, deterministic citation checks, one evidence retry, human review pause (approve / one revise / reject), graph events, in-memory checkpoint hook. No Milestone 3 Postgres, queue, or SSE endpoint.

### Owned files

- `backend/app/graph/**`
- `backend/app/research/**`
- `backend/app/schemas/research.py` and `backend/app/schemas/__init__.py`
- `backend/tests/test_graph_workflow.py`, `test_citations.py`, `test_retrieval.py`, `graph_fakes.py`
- `backend/scripts/live_text_smoke.py`
- `backend/requirements.in`, `backend/requirements.txt` (langgraph pin only; M1 pins kept)
- `docs/ADR/0003-langgraph-evidence-graph.md`
- `docs/IMPLEMENTATION_STATUS.md`

M1 provider modules were not rewritten.

### Decisions

- LangGraph `StateGraph` + `Send`, at most two workers per wave. See ADR 0003.
- Checkpointer is `InMemorySaver`. `build_checkpointer("postgres")` raises `NotImplementedError` until M3.
- Retrieved pages are data. Workers call a fixed search/fetch port; they do not let page text choose tools.
- A claim can be `supported` only after a stored passage quote overlaps it and the citation checks pass. Wording is "evidence assessed," not fact-checked.
- PDF parsing is off. PDF URLs keep the search snippet and say so.
- Provider JSON mode is not required. Completions are parsed as JSON and rejected when invalid.
- Model cost is always unknown (`estimated_cost_usd` is null). Unknown token usage is not coerced to zero.

### Tests run

```text
# V2 backend, Python 3.13.14 (/tmp/rm_v2_venv)
USE_MOCK_PROVIDER=true PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s backend/tests -v
Ran 47 tests in 0.431s — OK

# V1 regression (/tmp/rm_v1_venv)
/tmp/rm_v1_venv/bin/python -m unittest discover -s tests -v
Ran 13 tests in 0.633s — OK
```

**Pass counts:** backend 47/47 (23 previous M1 tests plus 24 new M2 tests), V1 13/13. No failures. No assertions weakened.

M2 tests cover worker-wave cap, planner truncation, invalid topic, provider timeout, malformed planner output, one evidence retry, search failure (not approvable), contradictions, prompt-injection fixtures, invented citations, one revision then a refused second revise, reject, and the Postgres checkpointer refusal.

### Live text smoke

Command (stdout only; stderr discarded; no secret values printed):

```text
PYTHONPATH=. /tmp/rm_v2_venv/bin/python backend/scripts/live_text_smoke.py
```

`.env` is present, gitignored, and was not staged. `USE_MOCK_PROVIDER` in that file is false. The script forced a live router. Key presence only: groq, gemini, mistral, openrouter, and tavily were all set. Tavily was not called.

`max_tokens=128` text completion:

| Role | Alias | Model | Result | Error class |
|---|---|---|---|---|
| planner | rm-planner | groq/openai/gpt-oss-20b | pass | |
| researcher | rm-researcher | groq/openai/gpt-oss-20b | pass | |
| verifier | rm-verifier | gemini/gemini-2.0-flash | fail | all_providers_unavailable |
| writer | rm-writer | groq/openai/gpt-oss-20b | pass | |
| eval_judge | rm-eval-judge | gemini/gemini-2.0-flash | fail | all_providers_unavailable |

A 16-token probe of the Groq model returned empty `content` with `finish=length` and reasoning text only, which `ModelClient` classifies as `unsupported_capability`. That probe is not the recorded smoke. At 128 tokens the same Groq model returned content.

A direct Router call for the Gemini roles raised `NotFoundError` with HTTP 404. The ModelClient maps that to `all_providers_unavailable`. The verifier's Mistral fallback did not produce a completion. Model IDs were not changed.

### Migrations / env vars

No database migrations. No new environment variable names. Graph bounds are code constants in `GraphLimits`, clamped to the source-of-truth ceilings.

### Known limitations

- Checkpoints and human-review resume exist only inside the process that compiled the graph. Restart loses them.
- An interrupted search or model call can run again. This is not exactly-once.
- SSRF protection is still V1's DNS check before `requests`, not connection-time enforcement.
- No PDF parser, no research-run HTTP API, no SSE endpoint, no Postgres job queue.
- `owner_id` is stored and not yet an authorization check.
- Live Gemini `gemini-2.0-flash` did not complete. Milestone 3 changes the default alias; see the M3 section. Do not treat that as a new live pass.

The checkpoint, run API, queue, and ownership bullets above describe the Milestone 2 handoff. Milestone 3 supersedes them. PDF parsing remains open. The security follow-up pins the urllib3 lookup; SSRF is still not closed.

## Blockers for M4

1. Parent/user acceptance of the M3 gate
2. Re-run a live completion for `gemini/gemini-flash-latest` before a public verifier/eval role depends on it
3. Do not start the React console until that review

---

## Milestone 3

### Assigned task

PostgreSQL-ready identity, jobs, events, evidence rows, usage ledger, idempotency, LangGraph checkpoints, one lifespan queue consumer, guest tokens, Turnstile verification hook, atomic one-use and global caps, ownership, and the run HTTP commands. Do not start Milestone 4.

### Owned files

- `backend/migrations/0001_identity_jobs_quota.sql`
- `backend/app/db/**`
- `backend/app/jobs/**`
- `backend/app/api/v1/**` (health extended; guest, runs, usage added)
- `backend/app/core/config.py` (quota, database, Turnstile, and Gemini alias defaults)
- `backend/app/main.py`
- `backend/app/graph/checkpointer.py` and a small `peek` / `continue_from_checkpoint` on the existing runner
- `backend/tests/test_jobs_quota.py`, `backend/tests/test_postgres_durability.py`
- `backend/requirements.in`, `backend/requirements.txt`
- `.env.example` (names and placeholder values only)
- `docs/ADR/0004-queue-and-persistence.md`
- `docs/IMPLEMENTATION_STATUS.md`

Graph node logic was not rewritten. The M2 test that expected `NotImplementedError` now expects the Postgres saver to fail closed until a connection is opened.

### Decisions

- ADR 0004. The filename `0003-queue-and-persistence.md` was already taken by the evidence-graph ADR.
- App SQL is applied from versioned files. LangGraph's own `AsyncPostgresSaver.setup()` migrates checkpoint tables. The worker uses sync `PostgresSaver` because the graph runner calls `invoke`.
- SQLite is the default test database. It enforces the one-use update and unique idempotency key. It does not implement `FOR UPDATE SKIP LOCKED`. A throwaway local Postgres cluster, started with `initdb` inside the test, covers skip-locked leases and checkpoint restart. The developer `DATABASE_URL` is not used and was not printed.
- `QUEUE_CONSUMER_ENABLED` defaults to true. The lifespan starts the single consumer only when that flag is true and a database is configured. Tests set the flag false and blank `DATABASE_URL`.
- Guest tokens are returned once. The database stores `sha256` only. Turnstile fails closed unless a secret is configured or a test double is injected.
- Refunds happen only when a job fails before `provider_work_started` is committed. Cancel consumes the one-use entitlement. Estimated cost stays null.
- `gemini/gemini-2.0-flash` stays on the allowlist. New defaults use `gemini/gemini-flash-latest`. No live Gemini call was made in this milestone.

### Tests run

```text
# V2 backend, Python 3.13.14 (/tmp/rm_v2_venv)
USE_MOCK_PROVIDER=true PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s backend/tests -v
Ran 65 tests in 1.885s — OK

# V1 regression (/tmp/rm_v1_venv)
/tmp/rm_v1_venv/bin/python -m unittest discover -s tests -v
Ran 13 tests in 0.652s — OK
```

**Pass counts:** backend 65/65, V1 13/13. No failures. No assertions weakened. The 65 includes the previous M2 tests, 16 new SQLite quota/API tests, and 2 Postgres tests (`SKIP LOCKED` leased two different jobs; a review pause resumed through a new `PostgresSaver` connection after `AsyncPostgresSaver.setup()`).

### Migrations / env names

- Migration: `backend/migrations/0001_identity_jobs_quota.sql`
- Checkpoint migrations: created at runtime by `AsyncPostgresSaver.setup()`, not checked in
- New env names: `DATABASE_URL`, `QUEUE_CONSUMER_ENABLED`, `QUEUE_POLL_SECONDS`, `JOB_LEASE_SECONDS`, `JOB_HEARTBEAT_SECONDS`, `JOB_MAX_ATTEMPTS`, `GLOBAL_MAX_ACTIVE_RUNS`, `GLOBAL_DAILY_RUN_CAP`, `MAX_MODEL_CALLS_PER_RUN`, `MAX_RUN_WALL_CLOCK_SECONDS`, `TURNSTILE_SECRET_KEY`, `TURNSTILE_VERIFY_URL`, `GUEST_TOKEN_TTL_HOURS`, `WORKER_ID`

### Known limitations

- SQLite cannot prove `FOR UPDATE SKIP LOCKED`. That behavior was measured only on a local throwaway Postgres, not on Neon.
- Graph checkpoints are durable only for a Postgres `DATABASE_URL`. SQLite persists jobs and events and keeps the graph saver in memory.
- A model call in flight when the process dies can run again.
- One guest token is not one human. Clearing the token and passing Turnstile again can create another identity.
- `GET /api/v1/research-runs/{id}/events` still returns JSON. Milestone 4 adds `GET /api/v1/research-runs/{id}/events/stream` for SSE replay and does not replace this route.
- `gemini/gemini-flash-latest` was not called. A deployment whose `.env` still sets `gemini/gemini-2.0-flash` will still receive HTTP 404 for those roles.
- The queue is one thread in the API process. It is not horizontal scaling.

### Parent review decision

Independent security review ([M3 security quota review](de429911-9066-4e4e-b8b5-26ced8d8bb0d)) returned **PASS WITH CONDITIONS**. The follow-up below addresses those conditions. M5 was not started.

---

## M3 security follow-up

Grok 4.7, authorized. Not Sonnet 5. `.env` was not read.

### Verdict

PASS WITH CONDITIONS stands as the review result. The conditions below are what this change did with them. SSRF is still open.

### Fixed

- Daily-cap refund uses `UPDATE quota_guard SET daily_count = daily_count - 1 WHERE id = 1 AND daily_window = :today AND daily_count > 0` in the same transaction as the entitlement refund. Four parallel decrements from a count of 2 stop at 0.
- `finalize_job` returns without writing unless `lease_owner` is exactly this worker. A null lease is not owned. `QueueConsumer.start` raises if another consumer thread is already alive in-process.
- Unset or blank `WORKER_ID` is `hostname-pid-random` (max 80 characters). A fixed `WORKER_ID` is still accepted when set.
- Null `expires_at` is expired. `POST /api/v1/guest-identities` sends `Cache-Control: no-store`.
- `TURNSTILE_VERIFY_URL` must be `https://challenges.cloudflare.com/turnstile/v0/siteverify`. An explicit port 443 is normalized to that URL. Any other host fails closed. Test doubles can still pass `allow_unpinned_url=True`.

### SSRF — left open

`tools.scrape_url` pins the global IPs from `validate_public_url` onto `socket.getaddrinfo` for that one urllib3 connection, including each manual redirect hop. V1 `test_connect_time_lookup_keeps_the_validated_address` sees `93.184.216.34` at connect time when a later lookup would return `127.0.0.1`.

This does **not** close SSRF. The pin is not an egress proxy. It does not cover connectors that skip `socket.getaddrinfo`, and it does not drop traffic to a public address. The required follow-up is a trusted egress proxy that dials only the checked IP and blocks private, loopback, link-local, and metadata ranges. Detail is in `docs/RISK_REGISTER.md` (R04).

### Still open from the review

- `gemini/gemini-flash-latest` was not live-called.
- `FOR UPDATE SKIP LOCKED` was measured on a throwaway local Postgres, not Neon.
- One guest token is not one human.
- A model call in flight when the process dies can run again.
- A deployment that still sets `WORKER_ID=api-1` shares that lease owner across processes. Leave it unset.

### Tests run

```text
# V2 backend, Python 3.13.14 (/tmp/rm_v2_venv), after the follow-up
USE_MOCK_PROVIDER=true PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s backend/tests -v
Ran 73 tests in 2.322s — OK

# V1 regression (/tmp/rm_v1_venv)
PYTHONPATH=. /tmp/rm_v1_venv/bin/python -m unittest discover -s tests -v
Ran 14 tests in 1.036s — OK
```

**Pass counts:** backend 73/73, V1 14/14. No failures. No assertions weakened. The 73 includes the previous backend tests, two SSE tests already in the tree, and the security tests added here. Both Postgres durability tests passed in this run (`SKIP LOCKED`, checkpoint reopen). A sandbox run that could not start `pg_ctl` is not the recorded result.

### Files

- `tools.py` — connect-time DNS pin for urllib3
- `backend/app/jobs/quota.py` — conditional daily decrement; null expiry rejected
- `backend/app/jobs/persist.py` — lease owner must match
- `backend/app/jobs/consumer.py` — refuse a second in-process consumer
- `backend/app/jobs/turnstile.py` — Cloudflare siteverify pin
- `backend/app/core/config.py` — unique worker id default; verify URL validator
- `backend/app/api/v1/guest.py` — `Cache-Control: no-store`
- `backend/app/research/retrieval.py` — comment only
- `.env.example` — `WORKER_ID` left unset
- `docs/RISK_REGISTER.md`, `docs/ADR/0004-queue-and-persistence.md`, this file
- Tests: `tests/test_tools.py`, `backend/tests/test_jobs_quota.py`, `backend/tests/test_config.py`

No migration. No new environment variable names. `frontend/**` was not edited in the security follow-up. `backend/app/api/v1/runs.py` was not edited.

---

## Milestone 4

### Assigned task

React + TypeScript + Vite Research Console, six screens, REST commands, and fetch-based SSE with `Last-Event-ID`. Grok 4.7, user-authorized. Not Sonnet 5. `.env` was not read.

### Owned files

- `frontend/**` (new SPA)
- `backend/app/api/v1/stream.py` (SSE only)
- `backend/tests/test_sse_stream.py`
- `backend/app/main.py` (router include only)
- `.github/workflows/tests.yml` (frontend job)
- `.gitignore` (`node_modules/`, `frontend/dist/`)
- `docs/IMPLEMENTATION_STATUS.md`

Jobs, quota, migrations, and the graph were not rewritten. The JSON events route is unchanged.

### Decisions

- Stream path is `GET /api/v1/research-runs/{run_id}/events/stream`. Bearer token and `Last-Event-ID` are headers. A token in the query string is ignored and does not authenticate.
- Each SSE `id` is the persisted `sequence_id`. A `snapshot` event is built on connect from `research_reports`, `research_sources`, `evidence_passages`, `research_claims`, and `usage_ledger`. It has no id, so it does not move the cursor. Null usage stays null. `estimated_cost_usd` is shown as unknown.
- The console reconciles with `GET /research-runs/{id}` after refresh, visibility return, and channel drop. It does not treat a dead channel as a live run.
- Markdown is passed through `react-markdown` without raw HTML. `<` is neutralized first. Citation ids become links to the evidence screen. Other URLs are text unless they are a stored source URL.
- Evaluation has no scores. Every metric is "not measured". There is no guest benchmark button.
- Server budgets are read-only. The start form cannot raise them.
- Guest token lives in `sessionStorage`. It is not put in the URL or the bundle.
- Local Vite proxies `/api` to `http://127.0.0.1:8000`. FastAPI does not send CORS yet.

### Env names (client)

- `VITE_API_BASE` — empty uses same-origin `/api`. Set an absolute origin only when that origin is allowed by the API.
- `VITE_TURNSTILE_SITE_KEY` — public site key. Empty shows a verification-token field. The server still accepts or rejects it.

No provider keys, database URLs, or `TURNSTILE_SECRET_KEY` are client settings.

### Tests run

```text
# Frontend, Node 24
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
eslint — pass
tsc --noEmit — pass
vitest run — 4 files, 16/16 pass
vite build — pass (dist/assets/index-DaVdvYvS.js 776.88 kB, gzip 235.38 kB; chunk-size warning)

# V2 backend, Python 3.13.14 (/tmp/rm_v2_venv), this sandbox
USE_MOCK_PROVIDER=true PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s backend/tests -v
Ran 71 tests in 1.996s — OK (skipped=1)
```

The skip is `PostgresDurabilityTests`: `initdb` failed in this sandbox (`CalledProcessError`). The M3 security follow-up recorded those two Postgres tests as passing when `pg_ctl` could start. This run did not weaken assertions. The 71 include the two new SSE tests and the security follow-up tests.

Browser check against `http://127.0.0.1:5173/` with no API on port 8000: desktop and a 390px viewport showed the cold-start banner, the verification form, and the mobile menu. A full research run was not clicked through because the API was down.

### Known limitations

- No separate REST routes for report, sources, or claims. The report and evidence screens use the SSE snapshot, with a truncated review-event draft only when the snapshot has no markdown.
- Publication date, passage relevance, and worker provider are unknown unless a stored field or event actually contains them.
- Cross-origin deployment needs CORS. It is not configured. Milestone 7 still owns that.
- The production JS chunk is large because Recharts and Markdown ship in one bundle.
- Playwright end-to-end against a live run was not run.
- DeepEval was not started in Milestone 4. The offline harness starts in the Milestone 5 evaluation half below.

---

## Milestone 5 — evaluation half

### Assigned task

Offline golden set, deterministic evaluators, and a DeepEval harness that cannot run on the public request path. Grok 4.7, user-authorized. Not Sonnet 5. `.env` was not read. Frontend, job queue, and backend application code were not edited.

### Owned files

- `evals/**` — dataset, fixture runs, deterministic checks, judge harness, tests
- `docs/evals/DATASET_CARD.md`, `docs/evals/RESULTS.md`, `docs/evals/failure-analysis.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `.gitignore` — `evals/results/` and `.deepeval/`

`evals/requirements.txt` pins `deepeval==4.3.3` and is not installed by CI or `backend/requirements.txt`.

### Decisions

- Dataset `golden-v0.1` has 32 author-reviewed questions, including multi-hop, contradictory, stale, current, insufficient-evidence, and prompt-injection cases. Passages are paraphrases. `snapshot_status` is `not_frozen`. `independent_second_review` is false. Expansion toward 50, frozen snapshots, and a second review are still open (`evals/DATASET_CARD.md`).
- Deterministic checks and LLM-judge metrics are separate. Judge rows use `kind: llm_judge`. Null scores are not zeros. Threshold 0.5 is DeepEval 4.3.3's library default, not a calibrated bar.
- The judge command requires `RM_EVAL_JUDGE=1` and `--confirm-offline`. It sets `DEEPEVAL_DISABLE_DOTENV=1`, `DEEPEVAL_TELEMETRY_OPT_OUT=1`, and `LITELLM_MODE=PRODUCTION` before import. It uses `deepeval.models.LiteLLMModel` with `gemini/gemini-flash-latest` and calls `metric.measure` only when `--dry-run` is absent. It does not call `deepeval.evaluate()`.
- Task Completion, Plan Adherence, and Step Efficiency stay skipped unless a saved run carries a trace. The public graph is not wrapped in DeepEval tracing. Contextual Precision and Contextual Recall are skipped for `TIME_DEPENDENT` reference answers.
- Fixture artifacts use `system: fixture`. They are not V1, V2-A, or V2-B outputs.
- Static URL checks do not resolve DNS and do not close SSRF.

### Tests run

```text
# Deterministic fixture self-check, Python 3.13.14 (/tmp/rm_v2_venv)
PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m evals.cli deterministic
dataset=32 runs=20 fixture_mismatches=0 unlabeled_issues=0
exit 0

# Eval unit tests, same interpreter. DeepEval is not installed in this venv.
PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s evals/tests -v
Ran 14 tests in 1.969s — OK
```

The 14 include a dry run that loaded DeepEval 4.3.3 from `/tmp/deepeval_inspect` and constructed `LiteLLMModel` plus the nine metric classes. Every score in that report was null. A sentinel `.env` was not copied into the output. No live judge completion was made. V1 and backend suites were not re-run because this half did not change their code.

### Known limitations

- No V1 versus V2-A versus V2-B comparison and no judge scores. `docs/evals/RESULTS.md` records that explicitly.
- Office-holder notes are dated 2026-11-07 and must be re-checked before any scored run.
- DeepEval is not in the project virtualenv. A controlled judge run needs `uv pip install --python /tmp/rm_v2_venv/bin/python -r evals/requirements.txt` plus an exported Gemini or Google key. That install was not done here.
- Quota and URL checks score saved artifacts and URL strings. They do not execute the PostgreSQL quota gate or `tools.validate_public_url`.
- GitHub Actions does not run `evals/tests`. That is intentional.

This half stopped before Milestone 6. The remote MCP work is recorded below.

---

## Milestone 5 — observability

### Assigned task

Structured JSON logs and OpenTelemetry spans for request, quota, job, graph node, search/fetch, provider call, database operation, and report persistence. Record role alias, fallback, token usage, timing, configured retries, and error class. Redact secrets, authorization headers, prompts, and source text. The evaluation half above is unchanged. Grok 4.7, user-authorized. Not Sonnet 5. `.env` was not read.

### Owned files

- `backend/app/observability/**` (new)
- Light hooks: `backend/app/main.py`, `backend/app/api/v1/runs.py`, `backend/app/jobs/consumer.py`, `backend/app/jobs/quota.py`, `backend/app/jobs/persist.py`, `backend/app/graph/builder.py`, `backend/app/graph/runner.py`, `backend/app/research/retrieval.py`, `backend/app/research/evidence.py`, `backend/app/providers/client.py`, `backend/app/db/engine.py`
- `backend/tests/test_observability.py`
- `backend/requirements.in`, `backend/requirements.txt`
- `.env.example`
- `docs/IMPLEMENTATION_STATUS.md` (this section and the board row only)

`frontend/**` and `evals/**` were not edited. No migration.

### Decisions

- Telemetry events go to the `researchmind.telemetry` logger as one JSON object per line. Other loggers are unchanged. Tracebacks are not formatted into that line. This is runtime telemetry, separate from DeepEval scores.
- Default trace export is a no-op. `OTEL_TRACES_EXPORTER=console` prints redacted spans. `OTEL_EXPORTER_OTLP_ENDPOINT` plus `OTEL_TRACES_EXPORTER=otlp` (or the endpoint alone) attaches the OTLP HTTP exporter. `OTEL_SDK_DISABLED=true` forces no export. An `otlp` choice with an empty endpoint does not fall through to localhost.
- `OTEL_EXPORTER_OTLP_HEADERS` is left for the exporter. This code does not log the endpoint or those headers.
- Missing token counts and an unobserved retry count stay the string `unknown`. A provider-reported zero stays zero. `retries_configured` is the LiteLLM setting, not a measured attempt count.
- A LangGraph review pause is `status=paused`. It is not recorded as a failed span.
- Database spans record the SQL verb and dialect name only. Bound parameters and statement text are not attributes. Those lines are DEBUG.
- A provider or tool call that dies before its checkpoint can run again, so the same logical call can emit more than one span.

### Env names

- `OTEL_SDK_DISABLED`
- `OTEL_SERVICE_NAME` (default `researchmind`)
- `OTEL_TRACES_EXPORTER` (`none`, `console`, or `otlp`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` (optional)
- `OTEL_EXPORTER_OTLP_HEADERS` (optional, exporter-owned, not logged)
- `LOG_LEVEL` (default `INFO`)

### Tests run

```text
USE_MOCK_PROVIDER=true PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s backend/tests -v
Ran 85 tests in 2.129s — OK
```

**Pass count:** backend 85/85, skipped 0, failed 0. The 12 new tests are in `backend/tests/test_observability.py`. Both Postgres durability tests passed in this run (`SKIP LOCKED`, checkpoint reopen). V1 was not re-run. Eval tests were not re-run. No assertion was weakened. Telemetry lines from this run did not contain the bearer token, provider key shapes, or the lab page sentence.

### Known limitations

- OTLP export was not pointed at a live collector. Console export was not started during the suite. Tests capture spans with an in-memory exporter.
- Actual provider retry counts stay unknown unless a response exposes an integer retry field. This run did not see one.
- Quota spans include the stored identity id and run id. They do not include the bearer token or the topic text.
- Milestone 6 was not started in that session. The remote MCP work is recorded below.

---

## Milestone 6 — remote MCP

### Assigned task

Thin Cloudflare Worker at `mcp-server/` with Streamable HTTP MCP. Six tools forward to FastAPI. No LangGraph in the Worker. No deploy. Grok 4.7, user-authorized. Not Sonnet 5. `.env` was not read.

### Owned files

- `mcp-server/**` (Worker, tests, Wrangler config, README, generated `worker-configuration.d.ts`)
- `backend/app/api/v1/snapshot.py` (snapshot moved out of the SSE module)
- `backend/app/api/v1/stream.py` (calls the shared snapshot)
- `backend/app/api/v1/mcp_reads.py` (report, sources, claim evidence, evaluation summary)
- `backend/app/main.py` (router registration)
- `backend/tests/test_mcp_reads.py`
- `docs/ADR/0006-cloudflare-mcp.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `.gitignore` (`.dev.vars`, `.wrangler/`)

No migration. Frontend and `evals/**` were not edited. No new backend environment variable.

### Decisions

- Stateless `createMcpHandler` from `agents` 0.33.0 and `McpServer` from `@modelcontextprotocol/server` 2.4.0. Route `/mcp`. See ADR 0006.
- Auth is the existing guest bearer (RFC 6750), forwarded to FastAPI. FastAPI still enforces expiry, ownership, one-use, and global caps. OAuth discovery is not shipped. A second identity would not own the Postgres entitlement.
- Worker secret names: **none**. The only configuration name is the Wrangler var `RESEARCHMIND_API_BASE`.
- Read routes project stored rows. `GET /api/v1/evaluation/summary` returns the 2026-11-07 note that judge scores were not measured. It does not run DeepEval.
- Create is not retried inside the Worker. The same `idempotency_key` is how a timed-out start is reused.
- Edge caps are per isolate: 3 creates and 20 reads per 60 seconds per token hash. They are not the durable quota.

### Tests run

```text
# Worker, Node v24.14.0, from mcp-server/
npm test
Test Files  3 passed (3)
Tests  29 passed (29)

npm run typecheck
tsc --noEmit — exit 0

npx wrangler deploy --dry-run --outdir .wrangler/dry-run
wrangler 4.158.0
Total Upload: 1250.66 KiB / gzip: 217.63 KiB
Binding: env.RESEARCHMIND_API_BASE ("http://127.0.0.1:8000")
--dry-run: exiting now.
```

Wrangler was not on `PATH`. The project dev dependency is 4.158.0. The dry run did not upload a Worker.

```text
# Backend, Python 3.13 venv /tmp/rm_v2_venv, throwaway Postgres available
USE_MOCK_PROVIDER=true PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s backend/tests -v
Ran 88 tests in 2.284s — OK
```

**Pass count:** Worker 29/29, failed 0. Backend 88/88, skipped 0, failed 0. The 3 new API tests are in `backend/tests/test_mcp_reads.py`. Both Postgres durability tests passed in this run. V1 was not re-run. Eval tests were not re-run. No assertion was weakened. MCP Inspector was not run.

### Known limitations

- No public MCP URL. The Milestone 7 section records a later whoami check. The Worker was still not deployed.
- Clients that only support OAuth login cannot connect. Clients that can set a bearer header can.
- Edge limits reset with the isolate and are not global. Two isolates can both forward a create. Postgres still applies the one-use and global gates.
- A client that changes `idempotency_key` after a timeout can hit `quota_consumed` if the first POST committed. The Worker does not roll a job back.
- `get_evaluation_summary` is an authenticated read of a checked-in note. It is not a measured quality score.
- `npm audit --omit=dev` reported 0 production vulnerabilities. The full tree, including Wrangler, reported 3 (1 moderate, 2 critical). `npm audit fix --force` was not run.
- MCP Inspector steps are in `mcp-server/README.md` and were not executed.

---

## Milestone 7 — deployment artifacts

### Assigned task

Production-style student demo deployability: Docker backend, Render blueprint, static frontend config, CORS allowlist, MCP deploy attempt, and an honest deployment report. Grok 4.7, user-authorized. Not Sonnet 5. `.env` was not read. No commit and no push.

### Owned files

- `Dockerfile`, `.dockerignore`, `.python-version`
- `infra/docker-entrypoint.sh`
- `render.yaml`, `vercel.json`
- `backend/requirements-fetch.txt`
- `backend/app/core/config.py`, `backend/app/main.py` (CORS only)
- `backend/tests/test_cors.py`
- `.env.example`, `frontend/.env.example` (`CORS_ORIGINS` / `VITE_API_BASE` comments)
- `mcp-server/README.md` (deploy blocker)
- `README.md`, `docs/deployment-report.md`, `docs/IMPLEMENTATION_STATUS.md`

No migration. Graph, evals, and the research routes were not rewritten. No new secret.

### Decisions

- Health stays at `GET /api/v1/health/live` and `GET /api/v1/health/ready`. Render's health check uses the live path.
- Uvicorn target is `backend.app.main:app`, not `backend.main:app`. `WEB_CONCURRENCY` must be `1` or the entrypoint exits.
- `CORS_ORIGINS` is an exact origin list. Empty means no CORS middleware. `*` is rejected. `allow_credentials` is false. Allowed methods are GET, POST, and OPTIONS. Allowed request headers include `Authorization`, `Content-Type`, `Accept`, `Last-Event-ID`, and `Idempotency-Key`.
- `render.yaml` is one free Docker web service plus one static site. No `databases:` block. `DATABASE_URL` is `sync: false` for Neon. `autoDeployTrigger` is `"off"`.
- `vercel.json` is the other static host. Use one console, then put that origin in `CORS_ORIGINS`.
- `backend/requirements-fetch.txt` is installed with `pip --no-deps` so `langchain==1.4.7` does not replace `langgraph==1.1.10`.
- Region `oregon` and plan `free` are blueprint values. They are not a running service.

### Tests and checks

```text
USE_MOCK_PROVIDER=true DATABASE_URL= QUEUE_CONSUMER_ENABLED=false TURNSTILE_SECRET_KEY= \
  PYTHONPATH=. /tmp/rm_v2_venv/bin/python -m unittest discover -s backend/tests
Ran 95 tests in 2.293s — OK
```

**Pass count:** backend 95/95, skipped 0, failed 0. Seven tests are in `backend/tests/test_cors.py`. Both Postgres durability tests passed in this run. V1 was not re-run. Eval tests were not re-run. Frontend was not re-run. No assertion was weakened.

`render.yaml` validated against `https://render.com/schema/render.yaml.json` on 2026-11-07: 0 schema errors. `python3 -m json.tool vercel.json` succeeded.

`CI=1 npx wrangler whoami` (Wrangler 4.158.0) exited 1: not logged in, token expired, non-interactive. Deploy was not attempted.

Docker Desktop is not installed (`/usr/local/bin/docker` points at a missing app). Render, Vercel, and Neon CLIs are not on `PATH`. No public URL was created.

### Env names

New API name: `CORS_ORIGINS`. Frontend names unchanged: `VITE_API_BASE`, `VITE_TURNSTILE_SITE_KEY`. Worker name unchanged: `RESEARCHMIND_API_BASE`. Secret names are listed in `docs/deployment-report.md` and were not given values in git.

### Known limitations

- No Docker build, no image size, no container RSS, no local or Render cold-start number.
- No hosted health, SSE, quota, or restart check.
- Neon pooled versus direct `DATABASE_URL` was not retested for the LangGraph checkpointer.
- The container trusts `X-Forwarded-*` from any connecting peer (`--forwarded-allow-ips='*'`).
- Fetch packages are installed without their dependency solver. Import of `tools.py` was checked in a side directory against the existing API environment, not inside an image.
- A model call in flight during a restart can still be repeated.

### Parent review decision

Not accepted. The milestone's public-URL gate is unmet. Artifacts and the manual checklist are in `docs/deployment-report.md`.

