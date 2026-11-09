# ADR 0004 — Queue and persistence

- **Status:** Accepted for Milestone 3 implementation, pending parent review
- **Date:** 2026-11-07
- **Related:** ADR 0001, ADR 0003, source-of-truth §§6–8, implementation plan Milestone 3

ADR 0001 reserved the name `0003-queue-and-persistence.md`. Milestone 2 already published ADR 0003 for the evidence graph, so this decision is ADR 0004.

## Decision

1. **Schema.** Versioned SQL lives in `backend/migrations/0001_identity_jobs_quota.sql`. `apply_migrations` records filenames in `schema_migrations` and skips files that already ran. Tables cover guest identity hashes, one-use entitlements, a single `quota_guard` row, research jobs, idempotency keys, job events, sources, passages, claims, reports, and a usage ledger. LangGraph checkpoint tables are not in this file.

2. **Sessions.** SQLAlchemy 2 is the application session layer. `postgresql://` and `postgres://` are rewritten to `postgresql+psycopg://` for that engine only, because psycopg 3 is installed and psycopg2 is not. The LangGraph saver still receives the original libpq URL.

3. **Checkpoints.** When `DATABASE_URL` is a Postgres URL, startup calls `AsyncPostgresSaver.setup()` from `langgraph-checkpoint-postgres` 3.2.0. That creates and migrates `checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, and `checkpoint_writes`. The Milestone 2 runner is synchronous, so the worker opens a `PostgresSaver` on those same tables for `invoke`. The connection stays open for that job and is closed afterward. `build_checkpointer("postgres")` still fails closed; callers use `open_postgres_checkpointer`.

4. **SQLite is a test fallback, not the deployment database.** Unique constraints and the conditional entitlement update run on SQLite. `FOR UPDATE SKIP LOCKED` does not. The SQLite lease is one `UPDATE ... WHERE id = (SELECT ... LIMIT 1)`. A second connection blocks on SQLite's writer lock instead of skipping a locked row. Postgres `SKIP LOCKED` is covered by `backend/tests/test_postgres_durability.py`, which starts a throwaway local cluster with `initdb` when those client tools exist. That test does not use the developer `DATABASE_URL`. CI without Postgres client tools skips it.

5. **Queue.** One daemon thread starts from the FastAPI lifespan when a database is configured and `QUEUE_CONSUMER_ENABLED` is true (the default). A second `QueueConsumer.start()` in the same process raises if the first thread is still alive. It recovers expired leases, then leases with a short transaction, heartbeats, runs the existing graph, and writes the result. `finalize_job` writes only when `lease_owner` is exactly this process's worker id. A cleared lease is not treated as owned. This is not `FastAPI.BackgroundTasks`. An external model call can run again if the process dies before the node checkpoint or the completion row is committed. That is not exactly-once execution. Unset `WORKER_ID` becomes `hostname-pid-random` so two processes do not share `api-1`.

6. **Identity and Turnstile.** `POST /api/v1/guest-identities` checks a `TurnstileVerifier`, then returns a random opaque token once with `Cache-Control: no-store`. Only `sha256(token)` is stored. A row with null `expires_at` is expired. If `TURNSTILE_SECRET_KEY` is set, the verifier POSTs only to `https://challenges.cloudflare.com/turnstile/v0/siteverify`. Any other host is rejected at startup. If the secret is unset, verification fails closed. Tests inject `StaticTurnstileVerifier` or an `httpx.MockTransport` (`allow_unpinned_url` is test-only). This is one run per issued token, not one run per person.

7. **Quotas.** A conditional update consumes `demo_entitlements` for an identity. A second start with a new idempotency key returns 409. The same key and same topic returns the existing run with `reused: true`. A different topic with the same key returns 409. `quota_guard` is updated in one statement so the global active cap (default 1) and daily cap (default 3) cannot both succeed under two concurrent transactions. Per-run budgets are copied from server settings. A client field such as `max_model_calls` is ignored.

8. **Refund.** A failed job refunds the one-use entitlement and one daily slot only when `provider_work_started` is still false. The daily slot is `UPDATE quota_guard SET daily_count = daily_count - 1 WHERE id = 1 AND daily_window = today AND daily_count > 0` in the same transaction as the entitlement change. User cancel consumes the entitlement even if the worker has not started. After provider work starts, cancel, failure, and expiry keep the entitlement consumed.

9. **Ownership.** Get, events, cancel, and review load the job only when `owner_id` matches the bearer token's hash. A mismatch is 404.

10. **HTTP.** `POST /api/v1/research-runs` returns 202. `GET /api/v1/research-runs/{id}` and `GET /api/v1/research-runs/{id}/events` return JSON. The events route is the replay log for a later SSE milestone; it is not an SSE stream. Cancel, approve, revise, and reject are POST. `GET /api/v1/me/usage` returns caps and consumption without tokens or cost invented as zero. `GET /api/v1/health/ready` reports `database: not_configured`, `ok`, or `unavailable` (503). Database errors do not include the URL or driver text.

11. **Gemini id.** Google shut down `gemini-2.0-flash` on 2026-06-01. The Milestone 2 live smoke got HTTP 404 for `gemini/gemini-2.0-flash`. Defaults for the verifier, eval judge, and Gemini fallbacks now use LiteLLM's documented alias `gemini/gemini-flash-latest`. The retired id stays on the allowlist so an environment that still names it can boot. Milestone 3 did not re-run a live completion, so the new alias is not capability-verified.

## Consequences

- Jobs, events, and evidence rows survive a process restart on SQLite and Postgres. Graph checkpoints survive a new connection only on Postgres.
- A paused review is `review_required` and does not hold a lease. Approve, revise, or reject queues the same job again. The global active slot counts only `queued` and `running` (not `review_required`), so one guest awaiting review does not block every other start.
- `QUEUE_CONSUMER_ENABLED=false` serves the API without leasing work. A deployment that wants runs to finish must leave it true and set `DATABASE_URL`.
- No Redis, pgvector, WebSockets, or SSE in this milestone.
