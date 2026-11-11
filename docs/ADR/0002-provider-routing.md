# ADR 0002 — LiteLLM SDK Router and free-only role aliases

- **Status:** Accepted for Milestone 1  
- **Date:** 2026-11-07  
- **Related:** ADR 0001, source-of-truth §3

## Decision

Use the **LiteLLM Python SDK `Router` inside FastAPI** (not a separate LiteLLM Proxy) with:

- Role aliases: `rm-planner`, `rm-researcher`, `rm-verifier`, `rm-writer`, `rm-eval-judge`
- Config-only model IDs via environment variables
- Strict `FREE_MODEL_ALLOWLIST` plus paid-marker denylist for **role primary/fallback** deployments
- `ALLOW_PAID_MODELS` must remain false (startup fails closed if true)
- `num_retries=0` on the Router by default; at most one configured **free** fallback hop per role
- After that free chain is exhausted (timeout / rate-limit / unavailable), `ModelClient` may make **one** post-chain call to `META_LAST_RESORT_MODEL` (default `meta/muse-spark-1.3-contributor`) when `META_API_KEY` (or aliases) is set and last-resort is not disabled. Meta is **not** on the free allowlist and is not a role primary/fallback.
- `USE_MOCK_PROVIDER=true` for CI / offline tests

## Consequences

- Provider/model changes do not require graph/node edits.
- CI never consumes provider quotas.
- Live tool-calling / structured-output capability per provider remains **unverified** until credentials are available; illustrative free model IDs in defaults must pass capability tests before a public demo relies on them.
- Meta Muse Spark Contributor last-resort is the lowest-cost Spark chat tier; Contributor mode may allow Meta to train on prompts/completions. It is engineering last-hop resilience, not a marketed paid product tier.

**Update (2026-11-10):** The Meta last resort runs only when `META_LAST_RESORT_ENABLED=true`, a Meta key is set, and `META_LAST_RESORT_MODEL` is on `FREE_MODEL_ALLOWLIST`; `render.yaml` does not enable it. An empty provider reply now falls through to the role fallback model, and tokens are counted after failed calls. `gemini/gemini-2.0-flash` is no longer in the default allowlist, and an environment that names it fails at boot. The offline eval judge uses `meta/muse-spark-1.3-contributor` (`evals/__init__.py`), not `rm-eval-judge`.

**Update (2026-11-11):** Gemini and Mistral were removed after live runs: Gemini returned 503s and timeouts, Mistral returned 429s, and claims went unverified. The defaults are now:
- Groq `gpt-oss-120b` for planner and writer, and `gpt-oss-20b` for researcher.
- OpenRouter `nvidia/nemotron-3.5-super-vl:free` for verifier, so a different model family checks the claims.
- OpenRouter Nemotron as the free fallback for planner, researcher and writer. NVIDIA NIM is supported (`nvidia_nim/`) but not a default: its models 404'd or timed out in live probes.
- Meta Muse as the owner-approved paid last resort, now enabled (`META_LAST_RESORT_ENABLED=true`).
