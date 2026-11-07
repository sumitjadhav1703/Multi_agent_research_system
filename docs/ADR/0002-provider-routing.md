# ADR 0002 — LiteLLM SDK Router and free-only role aliases

- **Status:** Accepted for Milestone 1  
- **Date:** 2026-11-07  
- **Related:** ADR 0001, source-of-truth §3

## Decision

Use the **LiteLLM Python SDK `Router` inside FastAPI** (not a separate LiteLLM Proxy) with:

- Role aliases: `rm-planner`, `rm-researcher`, `rm-verifier`, `rm-writer`, `rm-eval-judge`
- Config-only model IDs via environment variables
- Strict `FREE_MODEL_ALLOWLIST` plus paid-marker denylist
- `ALLOW_PAID_MODELS` must remain false (startup fails closed if true)
- `num_retries=0` on the Router by default; at most one configured fallback hop per role
- `USE_MOCK_PROVIDER=true` for CI / offline tests

## Consequences

- Provider/model changes do not require graph/node edits.
- CI never consumes provider quotas.
- Live tool-calling / structured-output capability per provider remains **unverified** until credentials are available; illustrative free model IDs in defaults must pass capability tests before a public demo relies on them.
