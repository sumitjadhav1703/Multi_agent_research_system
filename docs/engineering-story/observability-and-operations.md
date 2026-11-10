# Observability and operations

**Code:** `backend/app/observability/*` — PARTIALLY IMPLEMENTED · VERIFIED offline (`test_observability.py`, 12 tests)  
**Deploy default:** `OTEL_TRACES_EXPORTER=none` in `render.yaml`  
**Principle:** app must work without paid APM.

---

## What exists

| Signal | Implementation | Status |
|---|---|---|
| Structured JSON logs | logging helpers | IMPLEMENTED |
| Trace / span helpers | OpenTelemetry API usage | IMPLEMENTED |
| Redaction | Strip secrets / sensitive patterns | IMPLEMENTED · VERIFIED |
| Middleware | Request correlation hooks | IMPLEMENTED |
| Research / job ids | Present on job rows & events | IMPLEMENTED |
| Token usage | `usage_ledger` | IMPLEMENTED |
| Retry / failure classes | Provider error mapping | IMPLEMENTED |
| Live OTLP collector | — | NOT VERIFIED / export off |
| Paid monitoring SaaS | — | NOT REQUIRED |

---

## Proposed trace shape

```text
research.run
  ├── planner
  ├── search
  ├── worker.1
  ├── worker.2
  ├── source.extract
  ├── evidence.extract
  ├── claim.verify
  ├── report.generate
  └── evaluation          # offline only; not on public path
```

Spans should carry run id, node name, provider/model alias when known, latency, and error class — **not** full prompts, API keys, or entire HTML bodies.

---

## Operations playbook (demo)

| Symptom | Check |
|---|---|
| Console “Unable to connect” | API awake? CORS origin exact? Turnstile keys? |
| ready returns 503 (`not_ready`, database `starting` or `unavailable`) | `DATABASE_URL` / Neon awake (scale-to-zero); DB init retries with backoff |
| 429 / provider errors | Free-tier RPM; fallback allowlist; do not enable paid |
| Quota errors | Expected after one guest run |
| Stale SSE | REST reconcile; Last-Event-ID; job terminal state |
| Duplicate model charges after restart | Known at-least-once; inspect attempts |

---

## Lightweight monitoring options

1. Render + Neon dashboards (free tier history limited).  
2. Structured logs drained optionally later.  
3. Synthetic cron hitting `/health/live`: the Cloudflare Worker cron (`*/10 * * * *`, `mcp-server/wrangler.jsonc`) does this. `.github/workflows/keep-api-awake.yml` is manual-only because GitHub throttled its schedule. Watch free instance-hours.  
4. OTLP only when an endpoint is configured deliberately.

Do not conflate observability spans with DeepEval quality scores.

---

## Known gaps

- No measured hosted trace backend  
- No alerting SLO  
- Heartbeat/SSE metrics not aggregated  
- Worker edge logs separate from API logs  

Status remains **demo-operable**, not “production observability complete.”
