# ResearchMind 2.0 — Risk Register

**Updated:** 2026-11-09 (Phase 1.2 in-process IP dial: R04 only)  
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
| R04 | SSRF DNS rebinding / connect-time TOCTOU in public fetch | High | Medium | **Partially mitigated, not closed.** One in-process fetch resolves each hop once, rejects private/loopback/link-local/metadata (including embedded and legacy literals), dials that global IP, sets Host/SNI to the original hostname, re-checks redirects, and caps size, time, and HTML type. No separate egress proxy, so other sockets in the process are not filtered. See the residual note below. | Backend + Security | **Open — partial in-process IP dial** |
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

Phase 1.2 replaces the process-wide `socket.getaddrinfo` pin with one fetch helper, `backend/app/security/egress_fetch.py`. `tools.scrape_url` uses it. V2 retrieval calls that same `scrape_url` after an earlier `validate_public_url` gate. The gate does not choose the dial address. The fetch resolves again and dials that result.

What the helper does:

- Allows only `http` and `https`, ports 80 and 443, with no userinfo.
- Rejects private, loopback, link-local, reserved, multicast, and non-global addresses. That includes metadata `169.254.169.254`, IPv4-mapped addresses, NAT64 `64:ff9b::/96` and IPv4-compatible embeddings of a blocked IPv4 address, and legacy literals `inet_aton` treats as private (`2130706433`, `0177.0.0.1`, `127.1`) even when another parser would disagree.
- Resolves a hostname once per hop. TCP connect uses `socket.connect` on that IP literal, not `create_connection` on the hostname, so a later DNS answer is not what gets dialed. TLS SNI and the Host header stay on the original hostname. Certificate verification stays on.
- Rejects known metadata and local names before DNS: `localhost`, `metadata.google.internal`, and the suffixes `.internal`, `.local`, `.localhost`, and `.localdomain`.
- Follows redirects itself, at most four hops. Each next hop is validated before it is dialed.
- Stops at 1 MB, per-hop connect/read timeouts, and a total deadline. Non-HTML types are not extracted.

What is still open:

- This is not a network egress proxy or a packet filter. Code that opens its own socket, and a bug that skips the helper, are not blocked on the network.
- A public IP that passes the check is still fetched. The dial stops the name from flipping to a private address before connect. It does not stop an open redirector on the public internet, a public SSRF gadget, or prompt injection in the page.
- The retrieval wrapper looks the name up once, then `scrape_url` looks it up again and dials the second answer. The second answer is checked before the dial. DNS can still change for the next request.
- The check runs in the application process. A compromised worker can ignore it.
- There is no destination allowlist beyond "global IP".

Required follow-up before calling fetch safe on a machine that can reach a private network: a separate trusted egress proxy, or an equivalent network policy, that connects only to the already-checked IP and drops private, loopback, link-local, and metadata destinations even if the application is wrong. Do not describe SSRF as closed.

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
