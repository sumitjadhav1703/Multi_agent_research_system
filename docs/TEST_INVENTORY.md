# ResearchMind test inventory

How to run the offline suites. These commands use mocked providers and local SQLite unless a test file says otherwise. They do not measure live provider quality, hosted latency, or LLM-judge scores. This is not a production-readiness claim.

Python for the V2 and eval commands is the local 3.13 virtualenv when it exists: `/tmp/rm_v2_venv/bin/python`. Otherwise use `python3` with `backend/requirements.txt` and `evals/requirements.txt` installed. The V1 suite needs the root `requirements.txt` packages (`streamlit`, `groq`, `bs4`). `scripts/run_offline_suites.sh` uses `V1_PYTHON` when set, then `/tmp/rm_v1_venv`, then `/tmp/rm_phase12_venv`, then the V2 interpreter if that interpreter can import those modules. Do not print `.env` or secret values. Leave provider keys unset for these runs.

## One offline command

From the repository root:

```bash
bash scripts/run_offline_suites.sh
```

That script forces `USE_MOCK_PROVIDER=true`, an empty `DATABASE_URL`, `QUEUE_CONSUMER_ENABLED=false`, and an empty `TURNSTILE_SECRET_KEY`. It refuses to start when `DATABASE_URL` is already set, so it does not talk to a hosted database. It runs the V1 suite, the V2 backend suite, the eval unit tests, and the deterministic fixture check. It does not run the judge.

Node suites stay opt-in because they need installed `node_modules`:

```bash
RUN_NODE_SUITES=1 bash scripts/run_offline_suites.sh
```

## Suite commands

| Suite | Command | What a pass shows |
| --- | --- | --- |
| V1 baseline | `PYTHONPATH=. python -m unittest discover -s tests -q` | Frozen Streamlit/pipeline tests under `tests/` still pass. |
| V2 backend | `USE_MOCK_PROVIDER=true DATABASE_URL= QUEUE_CONSUMER_ENABLED=false TURNSTILE_SECRET_KEY= PYTHONPATH=. python -m unittest discover -s backend/tests -q` | FastAPI, graph, quotas, SSE, MCP reads, provider mocks, and list-price cost estimate (`test_cost_estimate`). External providers are not called. |
| Frontend lint | `cd frontend && npm run lint` | ESLint on the Research Console. |
| Frontend types | `cd frontend && npm run typecheck` | `tsc --noEmit` over `frontend/src` (includes `*.test.ts` / `*.test.tsx`). |
| Frontend unit | `cd frontend && npm test` | Vitest. Progress, quota, citation, SSE, Usage ledger mapping, Report `downloadMarkdown`, Evaluation chart honesty. |
| Frontend build | `cd frontend && npm run build` | Typecheck plus Vite build (must stay green for Vercel). |
| MCP worker | `cd mcp-server && npm test` | Vitest for bearer rejection, tool surface, and the FastAPI forwarder. No live Worker deploy. |
| Eval unit tests | `PYTHONPATH=. python -m unittest discover -s evals/tests -q` | Golden-set shape and the judge gate. No model calls. |
| Deterministic eval | `PYTHONPATH=. python -m evals.cli deterministic` | Fixture runs against the golden set. The printed rows are `metric_kind=deterministic`, not judge scores. |

GitHub Actions (`.github/workflows/tests.yml`) runs the V1 suite, the V2 backend suite with `USE_MOCK_PROVIDER=true`, and the frontend lint, typecheck, Vitest, and build. It does not run the MCP worker, the deterministic eval CLI, or the judge.

## Judge (manual only)

The judge is not part of the offline matrix and must not run on a public request.

```bash
RM_EVAL_JUDGE=1 PYTHONPATH=. python -m evals.cli judge --confirm-offline
```

Without `RM_EVAL_JUDGE=1` and `--confirm-offline`, the command refuses to score. A judge run needs a configured evaluator key and spends provider quota. Do not treat a missing judge run as a score of zero. Record any real judge output separately, with the dataset, model, and date. `docs/evals/RESULTS.md` is the place for measured results; this inventory does not update it.

## Postgres-only checks

`backend/tests/test_postgres_durability.py` starts a throwaway local Postgres with `initdb`, `pg_ctl`, and `createdb`. If those tools are missing or the cluster does not start, the class skips. The SQLite suite does not prove `FOR UPDATE SKIP LOCKED`. Do not point this file at Neon from the offline script.

## Source-of-truth §16 map

| Expected case | Where it is covered | Still thin |
| --- | --- | --- |
| SSE `Last-Event-ID` replay | `backend/tests/test_sse_stream.py` | Replay is SQLite-backed. A browser reconnect against the public API is not part of this suite. |
| Concurrent duplicate start | `test_simultaneous_starts_create_one_run` in `backend/tests/test_jobs_quota.py` | Two threads share one identity at the service layer. SQLite does not prove Postgres row locks. |
| Idempotency conflict and per-owner keys | `test_same_key_different_topic_conflicts_and_keys_are_per_owner`, `test_idempotency_conflict_and_cancel_after_work_consume_quota` | Same limit: SQLite, not Neon. |
| Cross-owner access denied | Run, events, cancel, SSE, report, sources, claims, and review actions | Denial is HTTP 404 `run_not_found`, so a hidden run is not confirmed. HTTP 403 is Turnstile failure or a missing entitlement, not the cross-owner status. |
| Provider 429 then one fallback | `test_primary_429_falls_back`, `test_both_deployments_429_stop_after_one_fallback` | Mock router only. Live Groq/Gemini/Mistral failover is not measured here. |
| Cancel after provider work consumes the one-use quota | `test_cancel_after_provider_work_keeps_the_entitlement` and the HTTP cancel case in `test_jobs_quota.py` | The graph itself is not executed in that case; the test drives cancel plus finalize. |
| Prompt injection, citation checks, worker cap | `backend/tests/test_graph_workflow.py`, `test_citations.py` | Covered offline with fakes. |
| MCP authz | `mcp-server/src/auth.test.ts`, `forward.test.ts`, `backend/tests/test_mcp_reads.py` | No new MCP case in this pass. Missing bearer, quota exhaustion, and owner-scoped reads already fail closed. |
| Frontend disconnect | `frontend/src/pages/screens.test.tsx`, `frontend/src/api/sse.test.ts` | No Playwright pass in the offline script. |

## What these suites do not prove

- Live Groq, Gemini, Mistral, OpenRouter, or Tavily calls.
- DeepEval judge scores.
- Render, Neon, Vercel, or Cloudflare behavior, including cold starts.
- Connection-time SSRF isolation. URL checks in the suite are the current defense, not a closed finding.
- That two API processes can lease jobs safely. The durability class starts its own Postgres and skips when that cluster does not start.
