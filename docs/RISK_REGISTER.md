# ResearchMind 2.0 — Risk Register

**Updated:** 2026-11-07 (M5 evaluation half: R15 only)  
**Owners:** Parent orchestrator unless noted

Severity: Critical / High / Medium / Low  
Likelihood: High / Medium / Low

---

## Active risks

| ID | Risk | Severity | Likelihood | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| R01 | Parent not running Opus 5.5 High; silent fallback to Auto/Composer | Critical | High (observed) | User selects Opus 5.5 High in model picker; re-verify before M1; do not claim Opus ran | User + Parent | **Open — Gate 0 fail** |
| R02 | Claude Sonnet 5 coding subagents unavailable (weekly usage / credits) | Critical | High (observed) | Buy credits or wait for weekly reset; do **not** silently switch to Sonnet 5.5 or Grok without explicit user decision | User | **Open — Gate 0 fail** |
| R03 | Public Streamlit demo burns shared Groq/Tavily org quota (no auth/quota) | Critical (if public keys) | High | Keep V1 demo posture documented; V2 atomic one-use + global caps before public V2 URL | Security + Backend | Open (V1 known) |
| R04 | SSRF DNS rebinding / connect-time TOCTOU in `validate_public_url` | High | Medium | **Not closed.** `scrape_url` now reuses the global IPs from that lookup and, for the duration of one `requests.get`, serves them from `socket.getaddrinfo` so urllib3 connects to those addresses. See the residual note below. Required follow-up before a private-network deploy: an egress proxy that dials only the pinned IP and blocks private, loopback, link-local, and metadata ranges even if DNS changes. | Backend + Security | **Open — partial pin only** |
| R05 | Prompt injection via topic + retrieved HTML into agents | High | Medium | Structural isolation, tool allowlists, deterministic citation checks, injection fixtures in M2/M5 | Backend + Test | Open |
| R06 | Unsanitized Markdown rendering of LLM/source text in Streamlit | High | Medium | V2 React: sanitize Markdown; safe citation components; never raw HTML from models | Frontend | Open |
| R07 | Free-tier provider quota exhaustion / model ID churn (Groq, Gemini, Mistral, OpenRouter `:free`) | High | High | Capability matrix tests; fail-closed allowlist; no paid fallback; pin aliases in config | Backend | Open |
| R08 | Gemini unpaid data-use / human review terms | High | Medium (if used) | Public-data-only notice; never send private topics; document in UI | Parent + Frontend | Open |
| R09 | Exactly-once LLM execution misconception after crash mid-call | Medium | High | Document at-least-once provider calls; idempotent job lease + checkpoint after persist | Backend | Open (design) |
| R10 | Render Free spin-down / cold start breaks long SSE research runs | High | High | Single instance + Postgres durability; document wake behavior; upgrade only on measured need | Deploy | Open |
| R11 | Local Python 3.15 vs CI/README 3.13 drift | Medium | Medium | Pin Docker/Render to 3.13; ADR if changing | Backend | Open |
| R12 | LangGraph Postgres checkpointer schema via `AsyncPostgresSaver.setup()` vs app migrations | Medium | Medium | Call `.setup()` once; coordinate with versioned app SQL migrations; test empty + upgrade DB | Backend | Open |
| R13 | LiteLLM Router misconfigured to allow paid models | Critical | Medium | Startup validation of free-only allowlist; tests for paid path fail-closed | Backend + Test | Open |
| R14 | Parallel subagents overwrite shared contracts | High | Medium | Max 2 write agents; non-overlapping file ownership; worktrees when available | Parent | Open (process) |
| R15 | DeepEval LLM-judge cost on public path | Medium | Medium | M5 eval harness refuses without `RM_EVAL_JUDGE=1` and `--confirm-offline`. Not imported by the API. Not in CI. Still confirm no later milestone wires it into a request. | Test | Open |
| R16 | Cloudflare MCP Worker accidentally duplicates graph logic | Medium | Low | Thin authenticated forwarder only; security review before M6 merge | Backend + Security | Open |
| R17 | `gh` auth token invalid locally | Low | High (observed) | `gh auth refresh`; HTTPS clone works without it | User | Open |
| R18 | Kit/docs merged but uncommitted; accidental loss or dirty main | Medium | Medium | Commit kit+audit on feature branch after user approval; keep `main` deployable | Parent | Open |
| R19 | No V2 code yet — large delivery surface | Medium | Certain | Follow milestone gates; preserve V1 Streamlit until V2 tests pass | Parent | Accepted |

---

## R04 residual — SSRF is not closed

`tools.validate_public_url` still does one `getaddrinfo` and rejects any answer that is not a global IP. `tools.scrape_url` keeps that IP list and, while that one `requests.get` runs, replaces `socket.getaddrinfo` so urllib3's `create_connection` is given those IPs instead of a fresh lookup. Redirects stay manual: each hop is checked and pinned the same way. V1 tests cover a rebind that would answer the second lookup with `127.0.0.1`; the connect-time lookup in that test still sees the public address from the first check.

That pin is not an egress firewall:

- It only affects callers of `socket.getaddrinfo` during that locked `requests.get`. A client that connects by IP, or a future urllib3 that stops using `socket.getaddrinfo`, is not pinned.
- The patch is process-wide and serialized by a lock. It is not per-tenant isolation.
- A public IP that passes `is_global` is still fetched. The pin stops the name from flipping to a private address before connect. It does not stop an open redirector, a public SSRF gadget, or prompt injection in the page.
- DNS rebinding after the pin is removed can affect the next request. Each request checks again, then pins that answer.
- Private, loopback, link-local, and metadata answers are blocked only when this check sees them. There is no packet filter.

Required follow-up before calling fetch safe on a machine that can reach a private network: a trusted egress proxy that connects only to the already-checked IP and drops private, loopback, link-local, and metadata destinations even if DNS changes. Do not describe SSRF as closed.

---

## Platform / SDK verification notes (Gate 0)

Verified against official docs on **2026-11-07** (not exhaustive product QA):

| Topic | Finding | Source |
|---|---|---|
| LiteLLM SDK `Router` | Still the correct in-process approach for aliases/fallbacks; Proxy not required for first release | https://docs.litellm.ai/docs/routing |
| LangGraph Postgres | Package `langgraph-checkpoint-postgres`; `AsyncPostgresSaver.setup()` required; use `autocommit=True` + `dict_row` for manual connections | LangGraph checkpoint-postgres README / Context7 |
| DeepEval + LiteLLM | `deepeval.models.LiteLLMModel` exists; provider must be in model string | DeepEval LiteLLM integration docs |
| Render Web Service | Bind `0.0.0.0:$PORT`; free plan 0.1 CPU / 512 MB; ephemeral FS | https://render.com/docs/web-services |
| Cloudflare remote MCP | Documented Streamable HTTP + OAuth remote MCP on Workers | https://developers.cloudflare.com/agents/model-context-protocol/ |
| Turnstile | Server-side siteverify flow documented | https://developers.cloudflare.com/turnstile/get-started/server-side-validation/ |
| Neon free limits | Exact numeric caps **not re-measured** this session — treat as **UNVERIFIED** until checked against Neon dashboard/docs at M3 | — |

**Decision required before M1 provider wiring:** confirm which free Groq/Gemini/Mistral model IDs currently pass tool-calling + structured-output capability tests; pin only those that pass.

---

## Closed / accepted for V1 demo

| ID | Note |
|---|---|
| A01 | In-memory Streamlit state — accepted for V1; unacceptable as V2 durability |
| A02 | Shared deployer API keys — accepted for portfolio demo with disclosure |
