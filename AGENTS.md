# AGENTS.md: ResearchMind working guide

Read this file first. It is enough to understand the project and start working safely.
`README.md` is the public overview. This file is the working guide for an AI coding agent or a new contributor.

---

## 1. What this project is

ResearchMind is a **portfolio demo** of a bounded multi-agent research system.
- A guest asks one public research question in a React console.
- A FastAPI backend queues the run in Postgres.
- A LangGraph graph does the work: plan sub-questions, search the web (Tavily), fetch pages safely, extract claims, verify them against stored passages, and write a cited report.
- The run then pauses for human review. Progress streams to the browser over SSE.
- A Cloudflare Worker exposes the same runs as MCP tools.

There are two generations in the repo:
- **V2 (live product):** `backend/`, `frontend/`, `mcp-server/`, `evals/`.
- **V1 (frozen):** `v1/`, the original Streamlit app, tag `v1-baseline`. It is kept for reference only and is not deployed. Don't add features to it, but keep its tests green.

Owner context: this is a resume and portfolio project on free-tier hosting. Honesty about what is measured matters more than marketing claims.

---

## 2. Ground rules (never break these)

1. **Secrets.**
   - Never read, print, cat, log or commit `.env` or any secret value.
   - Keys live in `.env` locally (gitignored) and in the Render, Vercel, Cloudflare and GitHub dashboards.
   - Code may load env through settings or dotenv without displaying values.
2. **Free models first.**
   - `ALLOW_PAID_MODELS` stays `false`, and every role model must be in `FREE_MODEL_ALLOWLIST`.
   - Role primaries and fallbacks are free models. Don't add a paid model to them.
   - The only paid model is the owner-approved Meta Muse last resort (`META_LAST_RESORT_ENABLED=true` in production). It runs only after a role's free primary and fallback both fail.
3. **One worker.**
   - `WEB_CONCURRENCY` must be `1`, because each Uvicorn worker starts its own queue consumer.
   - `infra/docker-entrypoint.sh` refuses any other value.
4. **Honest claims.**
   - Never claim a test, live call or deploy passed without real output.
   - Don't call SSRF "closed" (risk R04 is open).
   - Don't claim a live Gemini or other provider pass without a fresh verified call.
   - If a model you were asked to use is unavailable or substituted, say so.
5. **Postgres is the source of truth.** Job state, events, quotas, evidence and checkpoints go in the DB, never only in memory.
6. **Bounded graph.** Keep the hard caps in `backend/app/graph/limits.py`. A change must not allow unbounded model calls, searches or fetches.
7. **Python 3.13** for the backend. 3.15 fails LiteLLM native builds.
8. **Ask when blocked** or when a decision is the owner's, rather than guessing through ambiguity.

---

## 3. System map

| Component | Code | Runs on | URL |
| --- | --- | --- | --- |
| API + queue consumer + graph | `backend/` | Render Free (Docker), Singapore, service `researchmind-api-sg` | https://researchmind-api-sg.onrender.com |
| Research Console (React) | `frontend/src/` | Vercel, under `/app` | https://researchmind-console.vercel.app/app/ |
| Landing page (static) | `frontend/landing/` | Vercel, at `/` | https://researchmind-console.vercel.app |
| MCP server | `mcp-server/` | Cloudflare Workers | https://researchmind-mcp.jadhavsumit534.workers.dev |
| Database | `backend/migrations/` | Neon Postgres, `aws-ap-southeast-1` | private |
| Offline evals | `evals/` | local / CI | n/a |

Health checks:
- `GET /api/v1/health/live` checks the process only, with no DB call.
- `GET /api/v1/health/ready` checks the DB and returns `status`, `database`, `use_mock_provider`.

---

## 4. How a run flows

1. **Guest identity.**
   - The console solves Turnstile, then `POST /api/v1/guest-identities` returns a bearer `guest_token`.
   - Each identity gets one run (`demo_entitlements`).
2. **Start.**
   - `POST /api/v1/research-runs` with an `Idempotency-Key` header.
   - `backend/app/jobs/quota.py` checks the entitlement, the global active cap and the daily cap, inserts a `queued` job, then wakes the consumer.
   - Returns `202`.
3. **Consume.**
   - `backend/app/jobs/consumer.py` (a thread started in the FastAPI lifespan) leases the job with `lease.py`: `FOR UPDATE SKIP LOCKED` on Postgres, an equivalent on SQLite.
   - It heartbeats the lease. If the lease is lost, the graph stops early.
4. **Execute.**
   - `jobs/executor.py` builds the graph context and runs `graph/runner.py`.
   - The runner streams graph steps and checks the wall-clock deadline and lease-loss between steps.
5. **Graph** (`graph/builder.py`, nodes in `graph/nodes.py`):
   `validate → plan → schedule → worker (≤2 parallel, Send) → merge → extract_claims → verify → evidence_gate → write → validate_citations → human_review → complete`, plus a `fail` node.
   - `evidence_gate` can loop back to `schedule` once for a follow-up search. This happens only when a source slot is free, and only for new URLs.
   - `human_review` uses a LangGraph interrupt, and the job becomes `review_required`.
   - Approve leads to `complete`. Revise rewrites once; a second revise returns to review with a warning. Reject ends the run as `rejected`.
6. **Persist.**
   - `jobs/persist.py` `finalize_job` writes the status, sources, passages, claims, report, usage and events.
   - It refunds the entitlement if a run failed before any provider work.
7. **Stream.** `api/v1/stream.py` serves SSE:
   - It replays saved events, then sends new events and a `snapshot` when state changes.
   - Heartbeat every 15 s, streams capped at 15 min (`stream.closed` with a reconnect hint), `Last-Event-ID` resume.
   - The stream closes on terminal runs.

Statuses:
- Active: `queued`, `running`. Paused: `review_required`.
- Terminal: `completed`, `failed`, `cancelled`, `expired` (wall clock), `rejected`.

Event types:
- From the graph: `run.accepted`, `planner.started`/`completed`, `worker.started`/`failed`/`completed`, `source.discovered`, `evidence.extracted`, `claim.verified`, `writer.started`, `review.*`, `usage.updated`, `warning`.
- From jobs: `run.queued`, `run.completed`, `run.failed`, `run.cancelled`, `review.requested`.
- Grep `emit(` and `_append_event` for the exact set.

Model roles (LiteLLM aliases, `providers/router_factory.py`):

| Role | Alias | Used in node |
| --- | --- | --- |
| planner | `rm-planner` | `plan` |
| researcher | `rm-researcher` | `extract_claims` |
| verifier | `rm-verifier` | `verify` |
| writer | `rm-writer` | `write` |

Each role has a primary and a `-fallback` model. Empty content from the primary also triggers the fallback (`providers/client.py`). Workers don't call an LLM: they search and fetch.

---

## 5. Where to change things

| Task | Files |
| --- | --- |
| Add or adjust an HTTP route | `backend/app/api/v1/*.py`, registered in `backend/app/main.py` |
| Change graph steps or routing | `backend/app/graph/builder.py`, `nodes.py`, `state.py` |
| Change prompts | `backend/app/graph/prompts.py` (untrusted web text is wrapped by `untrusted_block`) |
| Change limits/caps | `backend/app/graph/limits.py` (hard bounds) + `backend/app/core/config.py` (env) |
| Evidence ledger, citation checks, report assembly | `backend/app/research/evidence.py` |
| Search / fetch | `backend/app/research/retrieval.py` (Tavily), `research/fetch.py` (page scrape), `security/egress_fetch.py` (SSRF dial) |
| Models, fallbacks, allowlist | `backend/app/providers/*`, `core/config.py`, `render.yaml` env |
| Queue, leases, quotas, retention | `backend/app/jobs/*` |
| DB schema | new file in `backend/migrations/` (idempotent SQL, applied at boot by `db/migrate.py`) + `backend/app/db/models.py` |
| Logging / tracing / redaction | `backend/app/observability/*` |
| Cost estimate | `backend/app/cost_estimate.py` (approximate list price, not an invoice) |
| Console pages | `frontend/src/pages/*` (routes in `App.tsx`: `/`, `/runs/:id`, `/runs/:id/report`, `/runs/:id/evidence`, `/evaluation`, `/usage`) |
| Console data and SSE | `frontend/src/api/{client,sse,types}.ts`, `hooks/useRunChannel.ts`, `state/runStore.ts`, `domain/runView.ts` |
| Console styling | `frontend/src/index.css` (plain CSS with a small base reset; there is no Tailwind) |
| Landing page | `frontend/landing/` (copied to the build root by `frontend/scripts/copy-landing.mjs`) |
| MCP tools | `mcp-server/src/{tools,server,forward}.ts`, limits in `limits.ts`, config in `wrangler.jsonc` |
| Eval checks / dataset | `evals/checks.py`, `evals/dataset/`, published numbers in `docs/evals/published-summary.json` (single source) |
| CI | `.github/workflows/tests.yml` |

When changing the API contract, update `frontend/src/api/types.ts` and the MCP forwarders too.

---

## 6. Data model (Postgres / SQLite)

Tables, from `backend/migrations/0001_identity_jobs_quota.sql` plus index changes in `0002_index_cleanup.sql`:

- `guest_identities`: one row per guest. The id is a hash of the bearer token, so the raw token is never stored.
- `demo_entitlements`: the one-use run allowance per identity, with refund tracking.
- `quota_guard`: global active and daily counters.
- `research_jobs`: the queue and run state: status, lease, attempts, budgets, resume action, errors.
- `idempotency_keys`: one row per create request.
- `job_events`: ordered event log (`sequence_id`), which SSE replays.
- `research_sources`, `evidence_passages`, `research_claims`, `research_reports`: the evidence ledger and output.
- `usage_ledger`: model calls, tokens, search calls and estimated cost per run.

LangGraph checkpoints live in the Postgres checkpointer tables (`graph/checkpointer.py`), and the SQLite path uses an in-memory saver. Retention (`jobs/retention.py`) deletes finished runs, and reviews idle past `DATA_RETENTION_DAYS`, along with their checkpoints.

---

## 7. Commands

Setup:

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
(cd frontend && npm ci) && (cd mcp-server && npm ci)
```

Run locally (offline):

```bash
USE_MOCK_PROVIDER=true DATABASE_URL=sqlite:///./local.db QUEUE_CONSUMER_ENABLED=true \
  TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA \
  PYTHONPATH=. uvicorn backend.app.main:app --port 8000
cd frontend && npm run dev   # http://127.0.0.1:5173/app/
```

The `1x000…AA` value is Cloudflare's public always-pass test secret.

Notes on mock mode:
- The mock provider exercises the plumbing but can't produce a real plan, so mock runs end as `failed` with `planner_output_invalid`. This is expected.
- Full graph behavior is covered by tests using `backend/tests/graph_fakes.py`.

Tests:

```bash
scripts/run_offline_suites.sh                     # V1 + backend + evals
RUN_NODE_SUITES=1 scripts/run_offline_suites.sh   # + frontend + MCP
# The script uses $PYTHON / $V1_PYTHON if set. V1 needs v1/requirements.txt.
```

Individual suites:

```bash
USE_MOCK_PROVIDER=true DATABASE_URL= QUEUE_CONSUMER_ENABLED=false TURNSTILE_SECRET_KEY= \
  PYTHONPATH=. python -m unittest discover -s backend/tests
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
cd mcp-server && npm test && npx tsc --noEmit
```

Baseline counts (2026-11-10): backend 225, frontend 47, MCP 31, V1 16, evals 15. If a count drops, find out why before continuing.

Live checks (they need real keys and are never run in CI): `backend/scripts/live_text_smoke.py` and `backend/scripts/live_capability_matrix.py`.

---

## 8. Deploy and operations

- **Auto-deploys on merge to `main`:**
  - Render (API): `render.yaml` sets `autoDeployTrigger: commit`. Migrations run at boot.
  - Vercel (console): `vercel.json`.
  - MCP Worker: `.github/workflows/deploy-mcp-worker.yml`, on changes under `mcp-server/**`. It needs the GitHub secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
- **Where secrets live:**
  - Render: `DATABASE_URL`, provider keys, `TAVILY_API_KEY`, `TURNSTILE_SECRET_KEY`, `CORS_ORIGINS`.
  - Vercel: `VITE_API_BASE`, `VITE_TURNSTILE_SITE_KEY`.
- **Render Blueprint sync.** Services match by `name`. Confirm the dashboard service is `researchmind-api-sg` before syncing, or Render creates a duplicate.
- **Keep-warm.** The Worker has a `*/10` cron that pings `/health/live`. The GitHub `keep-api-awake.yml` is manual-only, because GitHub throttled its schedule to every few hours. Cold starts can still take up to a minute.
- **Neon cost.** The consumer polls every `QUEUE_POLL_SECONDS` (0.5) only while busy. When idle it waits `QUEUE_IDLE_POLL_SECONDS` (300), so Neon can scale to zero. Don't lower the idle value casually.
- **DB outage at boot.** The API retries init in the background with 5→60 s backoff, and `/health/ready` reports 503 until it connects.
- **Turnstile.** The siteverify hostname must be one of the `CORS_ORIGINS` hosts. A new console domain must be added to `CORS_ORIGINS`.
- **Empty or no-answer live runs** usually mean a provider is down or mock mode is on. Run the capability matrix before claiming a live provider path works.
- **After any deploy,** check `/health/ready`, load `/app`, and do one guest run in a browser.

---

## 9. Known open items

Check `docs/RISK_REGISTER.md` and `docs/BUG_INVENTORY.md` for the full list.

- **R04 SSRF:** fetching is an in-process checked-IP dial with a deadline, and there is no egress proxy. It stays open.
- **Postgres lease SQL:** it is tested only on SQLite in CI. `test_postgres_durability.py` needs a real Postgres URL.
- **Elapsed time:** `elapsed_ms` does not carry across a review resume.
- **OTel:** `observability/tracing.py` touches private OpenTelemetry SDK fields. Re-test it when upgrading OTel.
- **Readiness:** `/health/ready` doesn't detect a dead consumer thread (BI-P2-18, partial).
- **Free provider limits:** OpenRouter `:free` allows 50 requests/day without a one-time $10 credit purchase, and NVIDIA NIM (optional, not a default) failed live probes. Gemini and Mistral were dropped on 2026-11-11 after live 503s and 429s.

---

## 10. How the owner likes to work

- **Models.** The parent orchestrator should be Claude Opus 5.5 High. Coding, frontend and test subagents should use Claude Sonnet 5, pinned explicitly, when available. If a pinned model is unavailable, substituted or exhausted, stop and report honestly. Grok is authorized for coding subagents when Sonnet 5 weekly usage is exhausted.
- **Subagents.** Use them proactively with non-overlapping file ownership. Run at most two write-capable agents at once. Use local Mac tooling when useful.
- **Momentum.** Continue to the next step when the gate allows, but stop for milestone review rather than inventing pass evidence.
  - After a confirmed bug-fix wave or upstream merge, prefer commit and deploy over blocking on documented residual risks, unless asked to close them.
  - After pulling new branch changes into `main`, prefer a focused delta re-audit (especially LangGraph edges) over a full re-bash.
- **Delivery.** Branch plus PR for larger changes; the owner merges. Commit messages explain the why.
- **Regions.** Prefer Singapore or Pacific regions for Neon, Render and Vercel; avoid US/Oregon. Prefer git auto-deploy for every surface.
- **Product framing.** The site is a resume portfolio demo. The landing has no sign-in or login pages, and frontend polish beats auth-product UX.
- **Console style.** Match the landing hero art style:
  - Black background, Inter, Bubbledot / Geist Pixel display fonts, white pills.
  - Simple and answer-first, and desktop-width aware rather than a narrow mobile scroll.
  - Themed stage symbols and per-stage colors in the process pipeline. No green or default AI chrome, no emoji clutter.
  - Report-style collapsible sections for usage, sources, activities and workers.
  - Interrupt, approve and status controls in the top-right header.
  - The first Live visit may expand detail panels; returning from other tabs collapses toward answer-only.
- **UI verification.** After console UX changes, verify with Playwright or browser snapshots. Improve obvious UX within the locked theme without asking about every micro-decision.
- **Usage page.** It shows real `/me/usage` ledger totals. It shows a list-price cost estimate when tokens or search calls exist, and "unknown" only when nothing was measured.
- **Public repo.** Ship only deployable product artifacts:
  - No `.streamlit/`, `.cursor/` or `.impeccable/` (gitignored).
  - No local plan dumps in the repo root.

---

## 11. Docs map

| Doc | Use it for |
| --- | --- |
| `README.md` | Public overview, API table, setup |
| `docs/engineering-story/` | Design narrative per area (pipeline, retrieval, streaming, cost, security, eval, deploy) |
| `docs/ADR/` | Decisions (0001 architecture, 0002 provider routing, 0003 evidence graph, 0004 queue and persistence, 0006 MCP) |
| `docs/RISK_REGISTER.md`, `docs/BUG_INVENTORY.md` | Open risks and bugs (update when you fix or find one) |
| `docs/TEST_INVENTORY.md` | What each test suite covers |
| `docs/deployment-report.md` | Hosts, regions, deploy checks |
| `docs/IMPLEMENTATION_STATUS.md` | Milestone history (append, don't rewrite history) |
| `docs/evals/` | Eval results; `published-summary.json` is the single source of numbers |
| `docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md` | Original spec (historical plan, with notes where the build differs) |
| `v1/README.md` | Frozen V1 app |

---

## 12. Definition of done

- [ ] The relevant suites pass locally, and the counts are not lower than the baseline without a reason.
- [ ] No secret in the diff. `.env` untouched.
- [ ] Caps and the free-only rule still hold.
- [ ] Docs that describe the changed behavior are updated: README, this file, the risk and bug docs.
- [ ] Changes are on a branch with a PR, and CI is green (6 jobs).
- [ ] After merge: Render, Vercel and the Worker have deployed, `/health/ready` returns 200, `/app` loads, and one browser guest run works.
