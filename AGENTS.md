## Learned User Preferences

- Parent orchestrator should be Claude Opus 5.5 High; coding, frontend, and test subagents should use Claude Sonnet 5 as pinned in `.cursor/agents/` when available.
- If a required/pinned model is unavailable, substituted, or exhausted, stop and report honestly; never claim Opus or Sonnet ran when they did not. User authorized Grok for coding subagents when Sonnet 5 weekly usage was exhausted.
- Never read, print, log, cat, or commit `.env` or secret values; API keys stay local in `.env` (gitignored). Processes may load env via dotenv without displaying values.
- Ask the user when blocked or when a decision is needed rather than guessing through ambiguity.
- Do not edit the approved plan files themselves (including `ResearchMind_2_0_Deployment_Ready_Plan.md`); implement against them and keep todos in sync rather than recreating them.
- Prefer continuing to the next milestone when the current gate allows, while still stopping for milestone review rather than inventing pass evidence.
- Use project subagents proactively with non-overlapping file ownership; default to at most two concurrent write-capable agents; use local Mac tooling when useful.

## Learned Workspace Facts

- Workspace root is `/Users/sumitjadhav/Multi_agent_research_system/repo`; GitHub remote is `https://github.com/sumitjadhav1703/Multi_agent_research_system.git`.
- Authoritative ResearchMind 2.0 specs are `docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md`, `CURSOR_IMPLEMENTATION_PLAN.md`, and root `ResearchMind_2_0_Deployment_Ready_Plan.md`; track progress in `docs/IMPLEMENTATION_STATUS.md`.
- V1 Streamlit/pipeline baseline is frozen at git tag `v1-baseline`; keep V1 modules and offline V1 tests green while V2 grows beside them under `backend/`.
- V2 stack target: FastAPI + LiteLLM SDK Router (free-only allowlist, no paid fallback), LangGraph bounded research, PostgreSQL/Neon durable jobs/quotas/checkpoints, REST + SSE (no first-release WebSockets), React/Vite Research Console, thin Cloudflare MCP Worker, Render deployability with a public URL as definition-of-done.
- Prefer Python 3.13 for the backend locally; Python 3.15 failed LiteLLM native builds in this environment.
- LiteLLM Gemini id `gemini/gemini-2.0-flash` returned HTTP 404 (retired); point defaults at the current Flash alias and do not claim a live Gemini pass without a fresh verified call.
- SSRF defenses remain V1-level (DNS/scheme checks with residual DNS-rebinding/connect-time risk); do not document SSRF as closed without egress-proxy or equivalent hardening.
- Local Docker/Postgres is not always available; `FOR UPDATE SKIP LOCKED` lease behavior needs real Postgres and is not proven by SQLite-only paths.
