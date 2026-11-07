# ResearchMind 2.0 — Cursor Execution Plan

**Purpose:** Convert the approved ResearchMind 2.0 deployment-ready blueprint into a controlled, test-first implementation that Cursor can execute in milestones with an Opus parent orchestrator and Sonnet coding subagents.

**Repository:** `sumitjadhav1703/Multi_agent_research_system`  
**Canonical specification:** [`docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md`](docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md)  
**Primary outcome:** A public, deployable student-demo URL with measurable research quality, bounded cost, persistent jobs, an inspectable workflow, a modern React interface, and a protected remote MCP endpoint.

---

## 0. How Cursor must use this plan

This is an execution plan, not permission to skip repository inspection. The canonical source-of-truth document contains the full approved requirements, architecture, provider choices, database design, security controls, UI requirements, deployment profiles, evaluation plan, milestones, and acceptance criteria. Read it before proposing implementation changes.

### Precedence and change control

1. `docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md` is the approved product/architecture specification. Preserve **all** of its requirements.
2. This file defines how Cursor should execute that specification safely and incrementally.
3. Existing repository code and tests are evidence about the current implementation, not automatic proof that every proposed architecture decision is already implemented.
4. If the live repository conflicts with the source-of-truth plan, report the conflict and propose the smallest safe adaptation. Do not silently remove a requirement or replace an approved technology.
5. If a dependency, provider API, hosting feature, model ID, or SDK behavior has changed, verify it against current official documentation and record the source/date in an ADR before implementation.
6. Do not invent benchmark results, performance improvements, cost savings, provider capabilities, security guarantees, or completed deployment steps.

### Model and subagent roles

**Parent/orchestrator: Claude Opus 5.5, High effort**

The user will select Claude Opus 5.5 in Cursor's main model picker before starting the implementation session. Opus owns the end-to-end plan, architecture, sequence, task decomposition, subagent dispatch, API contracts, integration, conflict resolution, final review, and milestone acceptance. Opus should not spend its context writing every routine implementation file itself.

**Coding subagents: Claude Sonnet 5**

The custom agents in `.cursor/agents/` pin `claude-sonnet-5` for implementation, frontend work, and test work. Sonnet 5 is the coding workhorse: it writes production-quality code, tests, migrations, fixtures, documentation, and fixes within its assigned scope. The parent Opus agent reviews and integrates all work.

**Model selection is not guaranteed by a plan file alone.** The main chat model must be selected manually in Cursor. The custom subagent `model` field pins the intended model where Cursor plan/model availability allows it. Before implementation, verify that the parent is actually running Opus 5.5 and the coding subagents actually ran Sonnet 5. Inspect Cursor's model/task details. If the pinned model is unavailable or silently falls back, stop and report the actual model; do not pretend the requested model ran.

Cursor currently documents the model IDs `claude-opus-5-5` and `claude-sonnet-5`. Opus 5.5 is its latest Opus model in the current model documentation. Cursor currently recommends Sonnet 5.5 as a newer successor to Sonnet 5, but this project deliberately pins Sonnet 5 because that is the user's requested coding model. Do not silently change to Sonnet 5.5. Ask for an explicit decision if Sonnet 5 is unavailable. Third-party model usage may be billed separately from included Cursor usage; check the account's model availability and usage budget before a long run.

### Orchestration responsibilities

The Opus parent must:

- Read this file, the canonical source plan, repository README, source files, tests, CI workflow, Docker/deployment files, and Git status before editing.
- Use subagents proactively for repository audit, backend implementation, frontend implementation, tests, and independent security/deployment verification.
- Delegate self-contained tasks with exact file ownership, contracts, acceptance criteria, commands to run, and expected handoff format.
- Parallelize only independent tasks. Do not let two agents edit the same files or shared contracts concurrently.
- Use isolated worktrees/branches for parallel write-heavy tasks when supported. If isolation is unavailable, sequence overlapping changes.
- Ask implementers to return changed files, design decisions, tests run, results, known limitations, and any migrations/environment-variable changes.
- Review diffs and test output itself. A subagent saying “done” is not proof.
- Integrate one milestone at a time. Do not start a dependent milestone until its gate passes.
- Keep the user informed with concise milestone summaries and explicit blockers.
- Keep `docs/IMPLEMENTATION_STATUS.md` current after each milestone.

### Subagent budget / parallelism

Use a small team of focused subagents. Default maximum: **two write-capable coding subagents at once**, plus one read-only reviewer when the tasks are independent. Avoid launching every subagent for every small task; parallel contexts consume additional model usage and can increase integration cost.

Recommended division:

| Role | Model | Scope |
|---|---|---|
| Parent orchestrator / architect | Claude Opus 5.5 High | Plan, architecture, contracts, dispatch, integration, acceptance |
| Backend implementer | Claude Sonnet 5 | FastAPI, LangGraph, LiteLLM, Postgres, job queue, MCP API-facing backend |
| Frontend implementer | Claude Sonnet 5 | React/TypeScript UI, SSE client, report/evidence/evaluation screens |
| Test engineer | Claude Sonnet 5 | Unit/integration/e2e tests, fixtures, CI, benchmark harness and test fixes |
| Security/deployment reviewer | Claude Sonnet 5, read-only | SSRF, quota/auth, prompt injection, Docker, Render/Neon/Vercel/Cloudflare readiness |

### Non-negotiable implementation rules

- Do not rewrite the whole application in one pass.
- Preserve the current Streamlit pipeline as ResearchMind V1 / baseline until the new path passes its tests.
- Record a baseline benchmark before modifying research behavior.
- Keep the API, graph, providers, persistence, frontend, evaluation, and MCP boundaries separate.
- Keep secrets server-side. Never commit `.env`, API keys, OAuth secrets, Turnstile secrets, database URLs, or MCP bearer tokens.
- No paid provider fallback, automatic paid top-up, or hidden billing path. Free-only model allowlist is enforced server-side.
- One public demo run per authenticated account or issued guest identity, enforced atomically in PostgreSQL—not by disabling a button in React.
- Default public demo concurrency is one run globally; research fan-out is capped at two workers.
- Use SSE for live one-way progress. Do not add WebSockets or arbitrary webhooks in the first release.
- DeepEval is offline/controlled evaluation, not a per-public-request cost multiplier.
- Use PostgreSQL as the source of truth for jobs, leases, events, quotas, evidence, and checkpoints. Do not rely on local disk or process memory for durable state.
- Do not add Redis or pgvector in the first version without a measured requirement.
- Deployment is a required deliverable, not a future optional task. A public deploy URL and deployment report are release gates.
- No unsupported claim may be labelled supported. Citations must resolve to actual saved source records and evidence passages.
- Do not label the project “production-ready”. Describe it as a production-style student demo with explicitly documented limits.

---

## 1. First Cursor session: mandatory read-only audit

**Do not edit source code in the first pass.** Start in Cursor Plan or Ask mode with the parent set to Opus 5.5 High. Ask the parent to delegate independent read-only inspections where useful.

### Audit tasks

1. Confirm repository, branch, Git status, current commit, uncommitted changes, default branch, and whether the existing worktree is safe to modify.
2. Inventory the current source tree. Read `README.md`, `agents.py`, `pipeline.py`, `tools.py`, `app.py`, requirements/lock files, tests, GitHub Actions, Streamlit configuration, and `docs/repair-plan.md`.
3. Run the existing offline test suite and frontend/build checks if any exist. Capture exact commands, versions, test counts and failures. Do not call real provider APIs during baseline tests.
4. Inspect the current Streamlit deployment and confirm its actual entry point, secrets mechanism, dependency/Python version, and current limitations.
5. Verify all external API/SDK calls that the V2 plan depends on using official current documentation: LiteLLM Router, LangGraph persistence/streaming, DeepEval metrics and LiteLLM integration, PostgreSQL checkpointer, Render web-service runtime, Neon PostgreSQL limits, Vercel static hosting, Cloudflare MCP/OAuth, Turnstile verification and Cursor subagents.
6. Identify all current V1 functions and tests that can be reused, wrapped, or retained.
7. Identify schema and architecture mismatches between the repository and the approved source plan.
8. Produce a dependency graph and a risk register.

### Audit deliverables

Create/update these files without changing existing application behavior:

- `docs/IMPLEMENTATION_STATUS.md` — milestones, status, owner/subagent, exact evidence, outstanding blockers.
- `docs/BASELINE_REPORT.md` — baseline test results, runtime versions, current app behavior, known gaps, and measured V1 metrics if available.
- `docs/ADR/0001-approved-architecture.md` — concise record that the canonical source plan is the accepted architecture.
- `docs/RISK_REGISTER.md` — technical/deployment/provider risks with mitigation and owner.

**Gate 0:** Parent Opus presents the audit findings, confirms test baseline, flags any changed provider/platform facts, and proposes the smallest implementation sequence. No implementation begins until the audit is complete and the existing V1 baseline is preserved.

---

## 2. Execution milestones

Each milestone must be delivered as a small, reviewable group of commits/changes. Before coding, Opus writes the task brief and acceptance checklist into `docs/IMPLEMENTATION_STATUS.md`. After coding, the test engineer and relevant read-only reviewer independently validate it. Opus reviews the diff, test evidence, and deployment impact before marking it complete.

### Milestone 0 — Freeze V1 and capture baseline

**Primary owner:** Opus orchestrator  
**Subagents:** repository audit / test engineer / security reviewer (read-only)

Tasks:

- Tag or otherwise preserve the existing V1 state without rewriting Git history.
- Run and record current tests.
- Run a small, controlled baseline dataset through V1 only when valid provider credentials and quotas are available; otherwise clearly mark live metrics as not measured.
- Save report outputs and source metadata needed for a reproducible comparison, removing secrets and personal data.
- Record per-run search calls, model calls, tokens if exposed, latency, failures, and manual citation review where measurable.
- Ensure baseline tests remain runnable without API keys.

Acceptance gate:

- V1 code path remains available.
- Offline test baseline is recorded.
- Any live benchmark limitations are explicit.
- No V2 code has broken the original app.

### Milestone 1 — Backend foundation, configuration and LiteLLM

**Primary owner:** backend implementer (Sonnet 5)  
**Review:** test engineer + Opus

Tasks:

- Establish a clean Python package boundary (`backend/` or the smallest structure justified by the live repo audit).
- Add typed configuration with startup validation and `.env.example` updates.
- Integrate the LiteLLM Python SDK `Router` inside FastAPI; do not deploy a separate Proxy in the first release.
- Define role-based aliases for planner, researcher, verifier, writer and evaluation judge.
- Put provider/model IDs in configuration, not in graph nodes or prompts.
- Add provider capability tests for text completion, tool calling, structured output, timeout, token usage extraction and fallback behavior.
- Allow only explicitly approved free-tier provider/model combinations; paid fallback is disabled by default and must fail closed.
- Add bounded retry/backoff only for eligible transient errors. Do not retry authentication, invalid request, quota-exhausted or unsupported-capability failures blindly.
- Normalize provider errors and usage data. Unknown usage must remain unknown, not zero.
- Add a mock provider for tests so CI never consumes provider quotas.

Acceptance gate:

- All role aliases resolve through LiteLLM.
- Each selected provider passes the capability test required for its assigned graph role.
- Free-only allowlist is enforced by configuration validation.
- Failover is tested with primary success, primary 429, timeout, malformed output, and all providers unavailable.
- No paid fallback can occur implicitly.
- Existing V1 tests still pass.

### Milestone 2 — LangGraph workflow and evidence-first research

**Primary owner:** backend implementer (Sonnet 5)  
**Parallel support:** test engineer may build fixtures/evaluators against agreed Pydantic contracts; do not duplicate graph code.

Tasks:

1. Define strict Pydantic models for research plan, subquestions, source records, extracted passages, atomic claims, verification decisions, report sections and graph state.
2. Implement a planner that creates at most three research subquestions for the public demo.
3. Implement bounded fan-out with at most two workers. Each worker gets one subquestion and an allowlisted tool set.
4. Add search, canonical URL normalization, deduplication, source metadata extraction, bounded HTML fetch, text extraction and source provenance.
5. Add a small PDF path only if its limits, parser dependency, MIME/signature checks and deployment RAM have been tested; otherwise record it as later scope and do not imply PDF support.
6. Build an evidence ledger: source → passage → claim links, exact quoted text, content hash, URL, title, publication/access date, extraction method and caveats.
7. Verify claims against actual passages. Return `supported`, `contradictory` or `insufficient`; include rationale and evidence IDs. The verifier must not treat a model-generated opinion as evidence.
8. Add deterministic validation: source exists, URL matches, evidence passage is present, no duplicate source inflation, and status/evidence consistency.
9. Add one bounded re-search loop for material evidence gaps, then proceed with caveats rather than looping indefinitely.
10. Build the writer from the verified evidence ledger. Every important factual claim must reference one or more evidence IDs.
11. Keep human review as an explicit pause/approve/revise step, with at most one revision.
12. Add LangGraph checkpoint configuration hooks, but connect durable PostgreSQL persistence in Milestone 3.
13. Emit graph custom/update events suitable for later SSE streaming.

Acceptance gate:

- Graph is bounded and deterministic at its control-flow boundaries.
- Parallel worker count never exceeds two.
- Evidence IDs resolve to stored passage text and source metadata.
- Contradictions and insufficient evidence are visible in final output.
- No fake citations or unsupported `supported` status pass deterministic validation.
- One evidence-gap retry and one report revision are enforced by tests.
- Malicious instructions in retrieved web content cannot select tools or override system instructions in the test fixtures.

### Milestone 3 — PostgreSQL, jobs, quotas and durable recovery

**Primary owner:** backend implementer (Sonnet 5)  
**Review:** test engineer + security/deployment reviewer

Tasks:

- Use Neon PostgreSQL for persistent state; create versioned SQL migrations and indexes from the source plan.
- Add owner/guest identity, job, job-event, source, passage, claim, report, usage-ledger and idempotency records.
- Use PostgreSQL-backed LangGraph checkpoints; verify exact checkpointer package/version and schema migrations before coding.
- Implement a single bounded queue consumer within FastAPI lifespan for the first Render deployment. Do not use `FastAPI BackgroundTasks` as the durable job queue.
- Use short transactions and `FOR UPDATE SKIP LOCKED` (or a verified equivalent) to lease jobs. Persist lease owner, expiry, heartbeat, attempts and next-attempt timestamp.
- Recover expired leases on startup. Be honest that an external model call can repeat if the process dies before persisting its completion; do not claim exactly-once LLM execution.
- Implement guest identity or login as selected in the canonical plan; verify Turnstile server-side. Store hashed opaque guest identifiers, not raw tokens.
- Enforce the one-use entitlement atomically in PostgreSQL with a unique constraint/conditional update. Support reopening an existing run without consuming a new quota.
- Add `Idempotency-Key` handling for duplicate starts and concurrent-request tests.
- Enforce global max one active run, global daily run cap, per-run search/source/token/model-call/time limits, and cancel/stop behavior.
- Expose `GET /api/v1/me/usage` with safe, non-sensitive quota information.
- Define an explicit quota refund policy: refund only infrastructure failures before provider work begins; after paid/quota-bearing provider work starts, consume the entitlement unless a narrowly defined recovery rule says otherwise.

Acceptance gate:

- Two simultaneous start calls for the same identity create exactly one run.
- A used identity can retrieve its prior run but cannot create a second one.
- Restarting the backend recovers queued/expired jobs from Postgres.
- Checkpoints and events survive process restart.
- Job ownership checks prevent one identity reading another identity's run.
- Per-run/global limits are enforced in backend/database layers, not frontend-only state.
- DB failure produces a safe error and does not begin model calls.

### Milestone 4 — React frontend and SSE

**Primary owner:** frontend implementer (Sonnet 5)  
**Backend contract owner:** backend implementer  
**Review:** test engineer + Opus

Tasks:

- Implement React + TypeScript + Vite as a static SPA. Keep the frontend independent of provider SDKs and secrets.
- Follow the Research Console visual direction in the canonical source plan: dark graphite/navy, restrained cyan/blue, high contrast, accessible focus states, no gratuitous glassmorphism.
- Implement the six named screens: New Research, Live Run, Final Report, Evidence Explorer, Evaluation Dashboard and Run History/Usage.
- Implement REST calls using TanStack Query and the agreed versioned API contract.
- Implement SSE using fetch-based EventSource reader (such as `@microsoft/fetch-event-source`) when bearer headers/Last-Event-ID are needed. Do not place bearer tokens in query strings.
- Persist event IDs server-side, replay events after reconnect/refresh, and refetch job status as the source of truth.
- Render citation IDs through explicit safe UI components. Sanitize Markdown/HTML. Do not allow raw HTML from model/source content.
- Clearly display quota consumed, public-data warning, source/evidence limitations, provider fallback and estimated/unknown usage.
- Implement states for loading/cold start, identity/Turnstile required, quota consumed, queued/running, review required, reconnecting, partial failure, insufficient evidence, completed, rejected, failed, cancelled and expired.
- Include a clear one-use demo notice and a way to reopen the existing run.
- Do not add WebSockets in this milestone.

Acceptance gate:

- Frontend builds and tests pass.
- Desktop and mobile layouts are usable and accessible.
- User can start one run, observe incremental SSE events, refresh, reconnect and continue from persisted state.
- Report citations open the correct saved source/evidence item.
- Another user's run cannot be read from the UI/API.
- Frontend bundle and network traffic contain no provider/database/MCP secrets.

### Milestone 5 — DeepEval and observability

**Primary owner:** test engineer (Sonnet 5) for eval harness; backend implementer for trace hooks  
**Review:** Opus

Tasks:

- Build the manually reviewed 30–50-query dataset described in the source plan. Include multi-hop, contradictory, stale-source, current-information, insufficient-evidence and prompt-injection cases.
- Evaluate V1, V2-A (planner + multi-source + evidence ledger) and V2-B (V2-A + claim verification) against equivalent questions and source snapshots where possible.
- Integrate DeepEval metrics: Faithfulness, Answer Relevancy, Contextual Precision, Contextual Recall, Task Completion, Plan Adherence, Step Efficiency, Tool Correctness and Argument Correctness as appropriate to the trace/data each metric requires.
- Integrate DeepEval with LiteLLMModel or a verified custom model wrapper. Pin evaluator model/alias and DeepEval version for comparable runs.
- Keep full evaluation manual/controlled. Do not run expensive LLM-as-judge evaluation on every public demo request.
- Add deterministic Python evaluators for citation/source integrity, evidence passage exactness, contradiction preservation, duplicate-source detection, quota enforcement and URL safety.
- Add OpenTelemetry spans and structured JSON logs for request, quota, job, graph node, search/fetch, provider call, DB operation and report persistence.
- Record provider/model aliases, fallback, token usage, timing, retry counts and error classes. Redact prompts, private source text, secrets and authorization data.
- Publish baseline comparison artifacts with dataset version, evaluator version/model, sample count, date and failure examples.

Acceptance gate:

- Evaluation is reproducible using a documented command.
- LLM-as-judge metrics and deterministic checks are not conflated.
- All scores have benchmark metadata and no invented results.
- Public requests do not trigger the full benchmark.
- Telemetry makes it possible to inspect a run without exposing secrets or unnecessary raw content.

### Milestone 6 — Remote ResearchMind MCP on Cloudflare Workers

**Primary owner:** backend implementer (Sonnet 5) or a narrowly scoped MCP implementer  
**Review:** security/deployment reviewer + Opus

Tasks:

- Implement a separate, thin remote MCP server using current Cloudflare Workers MCP guidance and Streamable HTTP transport.
- Expose only the approved tools from the canonical plan: create research run, get run, get report, list sources, get claim evidence and get evaluation summary.
- Forward only to authenticated FastAPI routes; do not duplicate LangGraph logic inside Worker code.
- Protect create-run with authenticated client identity and the same global/project usage quotas. Give read-only tools separate low request limits.
- Use OAuth or another documented secure client-auth pattern suitable for the intended MCP clients. Do not invent or ship a home-grown auth protocol if a supported flow exists.
- Validate tool inputs, cap response sizes, avoid returning secrets/private fields and implement timeouts.
- Test with MCP Inspector and at least one intended MCP client.
- Keep Worker secrets in Cloudflare secret bindings. Never place API keys in Worker source or the frontend.

Acceptance gate:

- Remote MCP endpoint is reachable over HTTPS.
- All exposed tools enforce authentication and ownership/authorization.
- Expensive create-run calls respect the one-use/global quota controls.
- Read-only tools return only the caller's authorized data.
- MCP Inspector tests pass and a failure in the Worker does not corrupt the underlying research job.

### Milestone 7 — Deployment, public demo and portfolio release

**Primary owner:** Opus orchestrator + deployment reviewer  
**Implementation:** Sonnet 5 backend/frontend subagents

Tasks:

- Build a portable Docker backend with pinned Python and dependencies. Use the current repo's verified runtime as a starting point; do not assume README versions are still current.
- Add `.dockerignore`, `Dockerfile`, `render.yaml`, health endpoints, environment validation and deployment documentation.
- Deploy exactly one Render Web Service / one Uvicorn worker initially, with one bounded PostgreSQL queue consumer in FastAPI lifespan.
- Bind to Render `$PORT`; do not hard-code production port; set `WEB_CONCURRENCY=1` for the first release.
- Use Neon rather than Render Free Postgres for durable state.
- Deploy React/Vite as Vercel Static or Render Static Site; set only public `VITE_API_BASE`. Configure exact backend CORS origins.
- Deploy Cloudflare Worker MCP separately.
- Verify Docker local run, health checks, readiness, CORS, REST, SSE incremental streaming, event replay, quota concurrency, restart recovery, provider outage/fallback and all-secrets server-side.
- Test Render Free cold-start and sleep/wake behavior; document it. If reliability/memory targets fail, upgrade only based on measured trigger criteria in source plan.
- Produce `docs/deployment-report.md` with deployed URLs, service plan/region, versions, resource observations, smoke-test results, known limitations and date. Do not commit secrets.
- Update README with architecture, screenshots, public demo link, setup, environment variables, tests, evaluation results, deployment profile and limitations.
- Create a short reproducible demo script/video outline and screenshots.

Acceptance gate:

- Docker build and container startup pass.
- Public frontend URL loads and calls the deployed backend.
- Public backend URL responds to live health checks.
- A full one-use research run completes or reaches a truthful partial/failure state.
- Browser refresh/reconnect and backend restart do not lose persisted state.
- One-use quota and global budget are enforced in the deployed environment.
- MCP remote endpoint is reachable and protected.
- Deployed p95 latency, memory, provider calls and token usage are recorded from actual test runs.
- README and deployment report match the actual deployed system.

---

## 3. Cross-milestone engineering standards

### API and schemas

- Agree versioned request/response schemas before frontend and backend implement the same contract.
- Prefer Pydantic models and explicit TypeScript types generated or kept in sync from an authoritative schema.
- Return structured error codes and safe messages; never expose raw provider traceback or secret-bearing exception strings.
- Use stable run IDs, event IDs, source IDs, claim IDs and idempotency keys.
- Keep owner scoping in every database/API query.

### Tests required with every feature

- Unit tests for pure logic and boundaries.
- Integration tests with mocked provider/search/database adapters where practical.
- Regression tests for every bug fixed.
- Negative tests for quota bypass, bad auth, malformed provider output, malicious pages, SSRF/redirects, duplicated requests and provider failure.
- Frontend tests for loading/error/empty/reconnect states.
- End-to-end tests for one complete research run, refresh/replay, one-use restriction and access isolation.
- A feature is not complete because a test file exists. The relevant commands must run and results must be reported.

### Database and migration standards

- All schema changes use versioned migrations.
- Migrations are deterministic and tested on an empty database and an upgraded database where possible.
- Use constraints to enforce invariants such as one-use entitlements and unique event sequence IDs.
- Avoid destructive migrations. Preserve V1 compatibility where practical.
- Never store raw guest tokens; store hashes.

### Provider standards

- Provider/model capability matrix is tested, not assumed.
- Keep model IDs in configuration.
- Use role aliases and per-stage token/time budgets.
- Disable all paid fallbacks and paid top-ups in the demo profile.
- Distinguish rate limits from temporary outages and invalid credentials.
- Use circuit-breaker/health state only if it is justified and testable; do not add complexity just for architecture diagrams.

### Streaming standards

- Start endpoint returns quickly with `202 Accepted` and a run ID.
- All events are persisted before/with delivery; use monotonically increasing IDs.
- SSE reconnect replays events after `Last-Event-ID`.
- Client always reconciles with persisted run status after reconnect.
- Heartbeats help detect stale streams but must not be used as a promise that Render Free will remain awake.
- No WebSocket in V1/V2 unless a concrete bidirectional low-latency requirement is demonstrated.

### Cost and resource standards

- Limit concurrency, sources, searches, model calls, output tokens and wall-clock runtime server-side.
- Never use a public UI setting as the only enforcement.
- Cache search/fetch outputs with a bounded TTL and clear freshness metadata.
- Keep DeepEval full benchmark separate from the public demo path.
- Do not run CPU-heavy PDF/OCR or large embedding work inside the Render request event loop.
- Track container RAM and CPU under the target workflow before increasing worker count or upgrading hosting.

---

## 4. Required progress artifacts

Cursor must maintain these artifacts while implementing:

```text
docs/
├── IMPLEMENTATION_STATUS.md
├── BASELINE_REPORT.md
├── RISK_REGISTER.md
├── deployment-report.md
├── ADR/
│   ├── 0001-approved-architecture.md
│   ├── 0002-provider-routing.md
│   ├── 0003-queue-and-persistence.md
│   ├── 0004-streaming-transport.md
│   └── 0005-hosting-and-deployment.md
├── evals/
│   ├── DATASET_CARD.md
│   ├── RESULTS.md
│   └── failure-analysis.md
└── screenshots/
```

Do not create empty documentation files just to make this tree look complete. Create each artifact when its milestone has real content.

`docs/IMPLEMENTATION_STATUS.md` should contain:

- Current milestone and status.
- Task ID and brief.
- Assigned subagent/model.
- Files changed.
- Commands executed and exact outcomes.
- Acceptance criteria passed/failed/not run.
- Blockers and follow-up tasks.
- Parent Opus review decision.

---

## 5. Commit and handoff discipline

- Work on a dedicated feature branch if the current worktree is clean and safe. Do not overwrite unrelated user work.
- Do not use destructive Git commands, force-push, reset, or rewrite history.
- Prefer small commits grouped by milestone. Do not commit secrets, local databases, model artifacts or generated build output.
- Do not automatically merge subagent worktrees until Opus has reviewed the diff and tests.
- If tests fail, report the actual failure; do not edit the test to make the failure disappear unless the test expectation itself is incorrect and the reason is documented.
- Keep `main` deployable. Do not merge a milestone that leaves the default branch in a broken state.
- Before final completion, run the full offline CI suite, frontend build, Docker build, database migration checks and deployment smoke tests that credentials/environment allow.

---

## 6. Definition of complete

The project is complete only when all are true:

- [ ] Existing V1 is preserved and has a recorded baseline.
- [ ] LiteLLM Router handles role aliases and tested free-only provider fallback.
- [ ] LangGraph supports bounded two-worker research, evidence ledger, claim verification, one bounded retry and human review.
- [ ] PostgreSQL persistence supports jobs, events, quotas, idempotency, evidence and durable graph checkpoints.
- [ ] One-use account/guest quota and global limits are enforced atomically.
- [ ] React Research Console implements all required screens and states.
- [ ] SSE events stream incrementally and replay correctly after reconnect/refresh.
- [ ] DeepEval benchmark and deterministic evaluators compare V1/V2 honestly.
- [ ] OpenTelemetry/structured observability records useful telemetry without leaking secrets or raw private input.
- [ ] Remote MCP endpoint is deployed, authenticated and tested.
- [ ] Docker/Render/Neon/frontend deployment works and produces a public demo URL.
- [ ] Backend restart recovery, quota-race test, provider failover and live SSE smoke tests pass.
- [ ] Documentation, screenshots, evaluation outputs and deployment report describe what actually exists.
- [ ] All known limitations and any unverified claims are clearly disclosed.

---

## 7. How to begin

1. Open the existing `Multi_agent_research_system` repository in Cursor.
2. Select **Claude Opus 5.5 High** in the main Agent model picker.
3. Confirm custom project agents from `.cursor/agents/` are available. Their `model` is pinned to **Claude Sonnet 5**.
4. Paste the complete prompt from [`CURSOR_START_HERE.md`](CURSOR_START_HERE.md).
5. Require the first session to complete Gate 0 read-only audit before any implementation.
6. After reviewing the audit, direct Opus to execute Milestone 0, then proceed one milestone at a time.

---

## 8. Current Cursor/Claude model references

Checked on **7 November 2026**. Model availability and Cursor billing depend on the user's Cursor account/plan and can change.

- [Cursor subagents documentation](https://cursor.com/docs/subagents) — project subagent files, model pinning, read-only agents, worktree isolation and orchestration patterns.
- [Cursor model: Claude Opus 5.5](https://cursor.com/docs/models/claude-opus-5-5) — model ID `claude-opus-5-5`; current Opus recommendation and coordinator strengths.
- [Cursor model: Claude Sonnet 5](https://cursor.com/docs/models/claude-sonnet-5) — model ID `claude-sonnet-5`; available coding model explicitly requested here.
- [Cursor model: Claude Sonnet 5.5](https://cursor.com/docs/models/claude-sonnet-5-5) — newer successor; informational only, not substituted in this plan.
- [Cursor Agent mode](https://cursor.com/help/ai-features/agent) — project agents, editing/testing, and review workflow.

The parent Opus model is selected in the Cursor UI; a repository file cannot guarantee which model Cursor actually runs. Check Cursor task details and usage records when model identity matters.
