# Cost and resource optimization

**Primary constraint:** student / portfolio demo with **no automatic paid LLM fallback** and minimal infra spend.

**Verification date for published free tiers:** 2026-11-08 (official docs; re-check before claiming “free”).

---

## Preferred stack (Profile A)

| Layer | Choice | Free-tier note |
|---|---|---|
| API | Render Free Docker | Sleep after 15 min; ~1 min wake; 0.1 CPU / 512 MB; 750 instance-hours/month ([Render free](https://render.com/docs/free)) |
| DB | Neon Free | 100 CU-hours/project/month; 1 GB storage/project; scale-to-zero 5 min ([Neon plans](https://neon.com/docs/introduction/plans)) |
| Console | Vercel Hobby | Static SPA; public env only |
| MCP | Cloudflare Workers Free | 100k req/day; 10 ms CPU ([CF limits](https://developers.cloudflare.com/workers/platform/limits/)) |
| Models | Allowlisted free providers | Quotas/RPM change; not “unlimited” |
| Queue | Postgres leases in API process | No paid Redis |

**Actual billed cost:** not published here. Treat as **$0 intended** until a dashboard invoice says otherwise. Bandwidth overages on Render can suspend free services if no payment method.

---

## Distinguish four numbers

| Term | Meaning |
|---|---|
| Free-tier entitlement | What the vendor includes at $0 |
| Actual resource usage | CU-hours, instance-hours, tokens used |
| Estimated cost | Model $ if prices known — often **null** in app |
| Actual billed cost | Invoice |

ResearchMind stores `estimated_cost_usd` as null when unknown — never fake $0.00 savings.

---

## Application-level spend controls — IMPLEMENTED

| Control | Mechanism |
|---|---|
| One free research run / guest identity | Postgres entitlement + Turnstile |
| Global active runs | `GLOBAL_MAX_ACTIVE_RUNS` (SoT demo: 1) |
| Global daily cap | `GLOBAL_DAILY_RUN_CAP` (SoT demo: 3) |
| Per-run model calls | `MAX_MODEL_CALLS_PER_RUN` + graph `max_model_calls` |
| Wall clock | `MAX_RUN_WALL_CLOCK_SECONDS` (zero budget honored — Codex P2) |
| Worker concurrency | ≤2 |
| Sources / searches / fetches | GraphLimits ceilings |
| Passage size | ≤500 chars, ≤2 / source |
| Dedup | URL + content hash |
| Router retries | 0 by default; ≤1 allowlisted fallback |
| Eval | Offline only |
| Logs | Redaction; no secret echo |

---

## When a free provider quota is exhausted

1. LiteLLM / provider returns rate-limit or auth errors.  
2. `ModelClient` maps errors; may try **one** allowlisted fallback.  
3. If all approved options fail → job fails safely; completed events/artifacts remain.  
4. **No** paid model is selected.  
5. Guest may have already consumed the one-use entitlement if provider work started — refunds only before that commit (quota rules).

---

## Caching

| Idea | Status |
|---|---|
| Cross-run semantic cache | DEFERRED (complexity + stale web) |
| HTTP fetch cache | NOT IMPLEMENTED as durable cache |
| Dedup within run | IMPLEMENTED |

---

## Storage retention

Jobs, events, evidence live in Neon (1 GB free cap/project). Render disk is ephemeral — never the source of truth.

**IMPLEMENTED:** `DATA_RETENTION_DAYS` defaults to **2**. On API startup and about once per hour in the queue consumer, ResearchMind deletes:

- `research_jobs` with `created_at` older than the cutoff, plus child events/sources/passages/claims/reports/usage/idempotency rows  
- Orphan `guest_identities` (and entitlements) with no remaining jobs **only after** `expires_at` (so a Turnstile guest can still start within `GUEST_TOKEN_TTL_HOURS`)  
- Best-effort LangGraph checkpoint rows by `thread_id` on Postgres  

`quota_guard` is never deleted. Batch size defaults to 100 jobs per pass. Disable with `DATA_RETENTION_ENABLED=false`.

---

## Minimum reliable interview-demo upgrade (if Free fails)

Only after **measured** triggers (OOM, CU-hour exhaustion, unacceptable cold start for a live interview):

1. Render paid compute (removes sleep) — smallest instance that holds peak RSS.  
2. Neon Launch if CU-hours/storage insufficient.  
3. Keep LiteLLM free allowlist unless budget explicitly approved.

Do not upgrade “for production feel” without numbers.

---

## What we refuse for cost theater

- Silent paid top-up  
- Fake $ savings in README  
- Running DeepEval judge on every public request  
- Extra Redis “because architecture diagrams look nicer”  
- pgvector before a corpus use case exists
