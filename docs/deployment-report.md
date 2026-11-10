# ResearchMind 2.0 deployment report

> **Mixed doc.** The live URL table and the dated follow-up measurements are the current deployed record. "What was verified", "What was not verified", "Demo script", and "Checklist before any public URL" are the 2026-11-07 pre-deploy record; the stack has since been deployed (Render `researchmind-api-sg`, Vercel, Cloudflare Worker, Neon). Superseded items carry a note. Current overview: [`README.md`](../README.md).

**Date:** 2026-11-07  
**Author:** Cursor Auto/Composer parent (deploy session). Earlier artifact author was Grok 4.7 (user-authorized), not Sonnet 5.  
**Profile intended:** Profile A — one Render Free web service, Neon Postgres, one static frontend, one Cloudflare Worker.  
**Region target:** Singapore / Asia Pacific (user request after the first US deploy).

## Live public URLs (Singapore)

| Surface | Region | URL | Smoke check |
|---|---|---|---|
| API (Render Free Docker) | `singapore` | https://researchmind-api-sg.onrender.com | `GET /api/v1/health/live` → 200; `GET /api/v1/health/ready` → 200 `database: ok` (`USE_MOCK_PROVIDER=true`) |
| Console (Vercel) | build/functions `sin1` | https://researchmind-console.vercel.app | HTTP 200 HTML shell |
| Neon Postgres | `aws-ap-southeast-1` (Singapore) | project `researchmind-2` / `lively-star-88380432` | Wired as Render `DATABASE_URL` (value not recorded here) |
| Cloudflare MCP Worker | workers.dev (edge) | https://researchmind-mcp.jadhavsumit534.workers.dev | Deployed via Wrangler OAuth after re-login. `RESEARCHMIND_API_BASE` set to Singapore API at deploy time. Version `14008bd9-6d25-4855-a339-9ad9d4d24161`. |

**Removed / superseded**

- Neon US West (`aws-us-west-2` project `autumn-mode-98666904`) — **deleted**.
- Render Oregon `researchmind-api` (`srv-dbnlo1c9v7es73d4at5g`, https://researchmind-api-o2tw.onrender.com) — **deleted by user** (API now 404; absent from Render service list).
- `render.yaml` region default is now `singapore`.

### Follow-up measurements (2026-11-10)

| Check | Result |
|---|---|
| Vercel production after `793f792` | Deploy `dpl_HuL5FwWPB7qvtHMfN3tgoVtdEpuE` **READY** (`sin1`); prior `b2e6b82` failed on `ReportPage.test.ts` tsc — fixed |
| GitHub Actions Tests | Run for `793f792` **success** (frontend + test jobs) |
| List-price cost estimate | Shipped in `b2e6b82` (`cost_estimate.py`); Render picks up via git auto-deploy when the API service is linked |
| MCP Worker | Git auto-deploy via `.github/workflows/deploy-mcp-worker.yml` (`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`) |
| Stale agent branch | `cursor/fix-empty-report-answer-8a03` **deleted** (content already on main) |
| Wipe handoff | Code/docs on GitHub `main`; secrets only in host dashboards — not in this repo |

### Follow-up measurements (2026-11-09)

| Check | Result |
|---|---|
| Post-deploy wake `/health/live` | HTTP 200, TTFB **0.340s**, total 0.341s (service already warm after retention-env deploy) |
| `/health/ready` | HTTP 200, TTFB **0.204s**, `database: ok`, `use_mock_provider: false`, `allow_paid_models: false` (as measured 2026-11-09; since 2026-11-10 `/health/ready` returns only `status`, `database`, `use_mock_provider`) |
| Warm second hit | live TTFB 0.275s; ready TTFB 0.181s |
| During-deploy probe | connection reset (~120s) while `dep-dbocmqrm8hqs7386s740` was building — expected Free-tier blip |
| Neon | project `lively-star-88380432`, branch `br-wandering-violet-a1ze5n7w`, endpoint host `ep-round-art-a1nye9fi` (direct) and `-pooler` host exists; `pooler_enabled: false` on compute. Connection string value not recorded. |
| Retention env on Render | `DATA_RETENTION_ENABLED=true`, `DAYS=2`, `INTERVAL_SECONDS=3600`, `BATCH_SIZE=100` merged; deploy became **live** |
| Live capability matrix | script `backend/scripts/live_capability_matrix.py`; keys present for groq/gemini/mistral/openrouter; **15/15 fail** `all_providers_unavailable`; raw Gemini `ServiceUnavailableError` **503** |
| Console | `https://researchmind-console.vercel.app/` and `/app/` HTTP 200 (screenshots via browser) |
| MCP unauth | POST `/mcp` without bearer → HTTP **401** |
| Container RSS / image size | still **not** measured (no local Docker Desktop) |

This report separates checks that ran from checks that did not.

## What was verified

| Check | Result |
|---|---|
| Backend unit tests | `USE_MOCK_PROVIDER=true DATABASE_URL= QUEUE_CONSUMER_ENABLED=false TURNSTILE_SECRET_KEY= PYTHONPATH=. python -m unittest discover -s backend/tests` — **95 tests, 2.293s, OK, 0 skipped**. Python 3.13.14. Includes the 7 CORS tests and both local Postgres durability tests. (Superseded 2026-11-10: backend 224 tests; V1 16, evals 15, frontend 47, MCP 31.) |
| CORS behavior | Exact origins are accepted. `*`, paths, and userinfo fail settings validation. An allowed origin is echoed on preflight and GET. Another origin is not. An empty `CORS_ORIGINS` adds no allow-origin header. Credentials are not enabled. |
| Fetch imports without moving LangGraph | `langchain==1.4.7` depends on `langgraph>=1.2.12`. The API pins `langgraph==1.1.10`. A dry-run with that pin as a constraint failed, as expected. Installing `backend/requirements-fetch.txt` with `pip --no-deps --target /tmp/rm_fetch_pkgs` and importing `tools.py` succeeded against the existing API environment. The venv pin was not replaced. (Superseded 2026-11-10: `backend/requirements-fetch.txt` is deleted; its packages are in `backend/requirements.txt` and scraping is `backend/app/research/fetch.py`.) |
| `render.yaml` schema | Downloaded `https://render.com/schema/render.yaml.json` on this date and validated the file with jsonschema. **0 errors.** `autoDeployTrigger` is quoted `"off"` because unquoted `off` is a YAML boolean. |
| Wrangler auth | `mcp-server` local Wrangler **4.158.0**, `CI=1 npx wrangler whoami`. **Not logged in.** The CLI said the auth token expired and could not be refreshed in a non-interactive shell. `npx wrangler deploy` was **not** run. |
| Docker | `/usr/local/bin/docker` is a symlink to `Docker.app`, and that application is not installed. `podman`, `colima`, and `orbctl` are not on `PATH`. **No image was built. No container was started. No image size, RSS, or local cold-start time exists.** |
| Render CLI | `render` is not on `PATH`. No `~/.render` config directory. **No Render service was created.** |
| Vercel CLI | `vercel` is not on `PATH`. No `~/.vercel` directory. **No Vercel project was created.** |
| Neon CLI | `neon` / `neonctl` are not on `PATH`. **No Neon database was created from this session.** |

`vercel.json` is valid JSON (the frontend rewrite file). It was not sent to Vercel.

## What was not verified

- `docker build` and `docker run` on macOS, and a `linux/amd64` image for Render.
- The container listening on `$PORT`, including Render's assigned port.
- `/api/v1/health/live` or `/api/v1/health/ready` on any public host.
- A browser on a deployed origin calling the API through `CORS_ORIGINS`.
- REST `202`, SSE incremental delivery, event replay, quota races, or restart recovery on Render or Neon.
- Render Free sleep, wake, memory, CPU, or cold start. The approved plan quotes Render's published free-tier spin-down (about 15 minutes idle, wake on the order of a minute). This session did not measure that.
- Provider fallback, token counts, or p95 latency on a hosted run.
- Whether a Neon pooled connection string works with the LangGraph Postgres checkpointer. `DATABASE_URL` is the only database setting. Pooled versus direct was not tested here.
- The Cloudflare Worker on a `workers.dev` hostname. `RESEARCHMIND_API_BASE` in `wrangler.jsonc` was still `http://127.0.0.1:8000` on 2026-11-07 (superseded: it is `https://researchmind-api-sg.onrender.com` and the Worker is deployed).
- Screenshots. None were captured because there is no deployed V2 UI.

## Artifacts

| File | Role |
|---|---|
| `Dockerfile` | Python 3.13 slim image. Installs `backend/requirements.txt` (bs4, soupsieve, tavily-python included; no langchain, no root `tools.py`; `requirements-fetch.txt` deleted 2026-11-10). No Docker `HEALTHCHECK`. Runs as uid 10001. Listens through `infra/docker-entrypoint.sh`. |
| `.dockerignore` | Keeps `.env`, frontend, MCP, evals, and tests out of the build context. |
| `infra/docker-entrypoint.sh` | Refuses to start unless `WEB_CONCURRENCY` is `1`. Binds `0.0.0.0:$PORT` (default `8000`). One Uvicorn worker: `backend.app.main:app`. |
| `render.yaml` | One Docker web service `researchmind-api-sg` (`plan: free`, `region: singapore`, `numInstances: 1`, health `/api/v1/health/live`). The duplicate `researchmind-console` static site was removed 2026-11-10; the console is on Vercel. No Render Postgres. `autoDeployTrigger` is `commit` (2026-11-10). |
| `vercel.json` | Console host (Vercel project; install and build run via `--prefix frontend`). Output is `frontend/dist`. Landing at `/`, SPA rewrites for `/app` and `/app/*`. Public env name is `VITE_API_BASE` only, plus the existing public `VITE_TURNSTILE_SITE_KEY`. |
| `.python-version` | `3.13` |
| CORS | `CORS_ORIGINS` on `Settings`. Empty means same-origin only. |

Startup already fails closed when `ALLOW_PAID_MODELS` is true, a role model is off `FREE_MODEL_ALLOWLIST`, a paid-model marker is configured, `TURNSTILE_VERIFY_URL` is not Cloudflare siteverify, or `WORKER_ID` is not one token of at most 80 characters. `CORS_ORIGINS` now also fails closed. `create_app()` reads settings when it installs CORS, so a bad allowlist fails at process start.

The entrypoint passes `--proxy-headers --forwarded-allow-ips='*'`. That trusts `X-Forwarded-*` from whatever connects to the container. It is there so Render's proxy can present HTTPS. It is not a pinned proxy allowlist.

The queue consumer still starts from the FastAPI lifespan when a database is configured and `QUEUE_CONSUMER_ENABLED` is true. An external model call in flight during a restart can run again. This deploy does not make provider calls exactly once.

## Demo script (not run)

Use this only after the URLs below exist. No step was executed against a public host.

1. Open the static console. Confirm it loads without a provider key in the page source.
2. Request a guest token (Turnstile, if `TURNSTILE_SECRET_KEY` and `VITE_TURNSTILE_SITE_KEY` are set).
3. Start one short research run. Expect HTTP `202` and a run id quickly, then SSE events.
4. Refresh the run page. The same run and earlier events should still be there.
5. Start a second run with the same guest. Expect the one-use quota error, and the first run still readable.
6. Restart the Render service during a queued or running job. The job row should still be in Neon. A model call that was in flight may repeat.
7. Call `GET /api/v1/health/live` and `GET /api/v1/health/ready` on the API origin.

## Checklist before any public URL

Do this in order. Values stay in the host dashboard or a local untracked `.env`. Do not commit them.

1. Install Docker Desktop (the current symlink is broken) and run:
   - `docker build -t researchmind-api .`
   - `docker run --rm -e PORT=8000 -e USE_MOCK_PROVIDER=true -e QUEUE_CONSUMER_ENABLED=false -p 8000:8000 researchmind-api`
   - `curl -fsS http://127.0.0.1:8000/api/v1/health/live`
2. Create a **Neon** database. Do not create Render Postgres. Put the connection string in Render as `DATABASE_URL`. Confirm whether the checkpointer needs the direct (non-pooled) Neon URL before relying on restarts.
3. Install the Render CLI, authenticate, and apply `render.yaml`, or create the same service by hand (the blueprint now defines only the API; the static console was removed). Leave autoscaling and extra instances off. Keep `WEB_CONCURRENCY=1`.
4. Deploy the API once so it has an HTTPS origin. `USE_MOCK_PROVIDER` is `false` in the blueprint, so a real run needs `GROQ_API_KEY` and `TAVILY_API_KEY`. Other provider keys are optional until that provider is used.
5. Set the static site's `VITE_API_BASE` to that API origin (no path, no secret) and deploy a Vercel project using `vercel.json`. Not both, unless `CORS_ORIGINS` lists every origin you actually serve.
6. Set the API `CORS_ORIGINS` to the exact console origin, for example `https://<console-host>`. Redeploy the API. Add `http://127.0.0.1:5173` only if a local Vite dev server calls the API directly instead of using the proxy.
7. Set `TURNSTILE_SECRET_KEY` on the API and `VITE_TURNSTILE_SITE_KEY` on the console if guest issuance should require Turnstile. Without the secret, guest behavior stays whatever the current API does when the secret is empty. Do not put the secret in Vite.
8. In a terminal, from `mcp-server/`: `npx wrangler login`. Change `RESEARCHMIND_API_BASE` to the public API origin, run `npm run cf-typegen`, then `npx wrangler deploy`. Do not deploy while the var is loopback. (Done: the var is the Singapore API origin; later deploys run from `.github/workflows/deploy-mcp-worker.yml`.)
9. (`render.yaml` now sets `commit`.) Turn `autoDeployTrigger` to `commit` only after a manual deploy has succeeded with the secrets set.
10. Record the real URLs, region, plan, cold-start time, and memory in this file. Delete any guessed number rather than filling one in.

### Environment names

API, server-side:

`DATABASE_URL`, `CORS_ORIGINS`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `TAVILY_API_KEY`, `TURNSTILE_SECRET_KEY`

Already set as non-secret values in `render.yaml` (change only if you mean to):

`WEB_CONCURRENCY`, `APP_ENV`, `ALLOW_PAID_MODELS`, `USE_MOCK_PROVIDER`, `QUEUE_CONSUMER_ENABLED`, `GLOBAL_MAX_ACTIVE_RUNS`, `GLOBAL_DAILY_RUN_CAP`, `MAX_MODEL_CALLS_PER_RUN`, `MAX_RUN_WALL_CLOCK_SECONDS`, `OTEL_TRACES_EXPORTER`, `OTEL_SERVICE_NAME`, `LOG_LEVEL`, `FREE_MODEL_ALLOWLIST`, and the `PLANNER_*` / `RESEARCH_*` / `VERIFIER_*` / `WRITER_*` / `EVAL_JUDGE_*` model names.

Leave `WORKER_ID` unset so each process gets its own lease owner.

Console, public build args only:

`VITE_API_BASE`, `VITE_TURNSTILE_SITE_KEY`

Worker, not a secret:

`RESEARCHMIND_API_BASE`

No new secret was written to git. `.env` was not read.

## Known limits

- One Render instance and one Uvicorn worker. This is a single-process demo. Free web services sleep and the disk is ephemeral. Jobs belong in Neon, not in the container filesystem.
- Keep-awake: a Cloudflare Worker cron (`*/10`, in `mcp-server`) pings `/api/v1/health/live`. `.github/workflows/keep-api-awake.yml` is manual only because GitHub throttled its schedule. Neon idle queue polling is `QUEUE_IDLE_POLL_SECONDS=300` so it can scale to zero. Not an SLA.
- Render Free was not upgraded. No memory or latency trigger was measured, so there is no basis to move to a paid plan.
- HTML fetch uses in-process egress-style IP dial (`backend/app/security/egress_fetch.py`) via `scrape_url` in `backend/app/research/fetch.py` (overall read deadline; no longer root `tools.py`). **No separate egress proxy** — R04 remains partially mitigated, not closed.
- Live Gemini on 2026-11-09 returned HTTP **503** (`ServiceUnavailableError`). Capability matrix is recorded as failed that day; re-run when the provider recovers. Do not treat a prior Flash-latest eval probe as a full role matrix pass.
- The Worker does not run the research graph. Edge rate limits are per isolate. Quota remains in FastAPI and Postgres. MCP OAuth is deferred (bearer guest only).
- No V1 vs V2 comparison exists. Offline fixture judge means (Meta Muse Spark, 2026-11-09) are published in `docs/evals/published-summary.json`; see `docs/evals/RESULTS.md`.
