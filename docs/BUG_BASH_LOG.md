# Bug bash log — ResearchMind 2.0 Singapore stack

**Date:** 2026-11-09  
**Surfaces:** Render API `https://researchmind-api-sg.onrender.com`, Vercel `https://researchmind-console.vercel.app`, MCP `https://researchmind-mcp.jadhavsumit534.workers.dev`, Neon `researchmind-2` / `aws-ap-southeast-1`.

| ID | Severity | Repro | Result / fix |
|---|---|---|---|
| BB01 | P2 | Live capability matrix all roles (`backend/scripts/live_capability_matrix.py`) | All 15 probes `all_providers_unavailable`. Raw Gemini Router call returned `ServiceUnavailableError` HTTP **503**. Documented; not a code crash. Retest when Gemini recovers. |
| BB02 | P1 (ops) | Idle Render Free wake via `/api/v1/health/live` during retention env redeploy | First probe during deploy: connection reset (~120s). After deploy `live`: live TTFB **0.34s**, ready **0.20s**, `database: ok`, `use_mock_provider: false`. Lifespan fail-soft + retention env applied. |
| BB03 | P3 | `POST /mcp` initialize without bearer | HTTP **401** unauthorized (Worker requires bearer even for initialize). Expected for current ADR 0006 bearer design. |
| BB04 | P3 | `POST /api/v1/research-runs` without auth | HTTP **401** `unauthorized`. |
| BB05 | P3 | `POST /api/v1/guest-identities` without `turnstile_token` | HTTP **422** field required. Turnstile gate intact. |
| BB06 | P3 | Forged bearer + forged run UUID | HTTP **401** invalid guest token. |
| BB07 | P2 (DX) | `npm run lint` in `frontend/` | Missing `globals` package for ESLint flat config. Fixed by adding `globals@16` devDependency. |
| BB08 | info | Console `/app` while API cold | UI shows **Waking…** then Enter demo. Matches free-tier wake UX. |
| BB09 | residual | SSRF R04 | In-process IP dial shipped; no separate egress proxy. Residual risk documented. |

## Security review (Phase 2.4)

Independent `security-deployment-reviewer` (Grok, authorized): **PASS WITH CONDITIONS**.

Conditions kept open: R04 partial SSRF; Gemini 503 matrix; no MCP OAuth; Render Free sleep; Neon pooler untested for checkpointer; full Turnstile→SSE run not consumed in bash.

Follow-up fixed in-tree after review: markdown images gated to allowlisted http(s) URLs in `MarkdownView`.

## Open P0 / P1 after bash

- **No open P0.**
- **P1 code:** none remaining after lifespan resilience + eslint `globals` fix + image allowlist.
- **P1 external:** Gemini 503 blocks live provider matrix and fuller judge runs until the provider recovers (ops/quota, not an app crash).

## Notes

- Full guest Turnstile → research run → SSE was not completed in this bash (would consume the one-use quota and needs a browser Turnstile token). Authz and health paths were exercised instead.
- MCP Inspector interactive UI was not launched; equivalent HTTP checks confirmed unauthenticated calls are rejected.
