## Learned User Preferences

- Parent orchestrator should be Claude Opus 5.5 High; coding, frontend, and test subagents should use Claude Sonnet 5 as pinned in `.cursor/agents/` when available.
- If a required/pinned model is unavailable, substituted, or exhausted, stop and report honestly; never claim Opus or Sonnet ran when they did not. User authorized Grok for coding subagents when Sonnet 5 weekly usage was exhausted.
- Never read, print, log, cat, or commit `.env` or secret values; API keys stay local in `.env` (gitignored). Processes may load env via dotenv without displaying values.
- Ask the user when blocked or when a decision is needed rather than guessing through ambiguity.
- Do not recreate large Cursor kit plan dumps in the repo root; implement against `docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md` and keep `docs/IMPLEMENTATION_STATUS.md` in sync.
- Prefer continuing to the next milestone when the current gate allows, while still stopping for milestone review rather than inventing pass evidence.
- Use project subagents proactively with non-overlapping file ownership; default to at most two concurrent write-capable agents; use local Mac tooling when useful.
- Prefer Singapore/Pacific (or nearest) cloud regions for Neon, Render, and Vercel; avoid US/Oregon placements when a Singapore or nearby option exists, for lower latency.
- Treat the public site as a resume portfolio demo: no Sign-in/login pages on the landing; frontend polish over auth-product UX.
- Match the entire Research Console to the landing hero art style (black, Inter, Bubbledot/Geist Pixel, white pills) and keep the inside simple to understand; avoid generic AI-dashboard chrome.
- Prefer a production-grade public GitHub tree: omit `.streamlit` and local Cursor/plan master docs from what is pushed; ship only deployable product artifacts.

## Learned Workspace Facts

- Workspace root is `/Users/sumitjadhav/Multi_agent_research_system/repo`; GitHub remote is `https://github.com/sumitjadhav1703/Multi_agent_research_system.git`.
- Authoritative ResearchMind 2.0 spec is `docs/RESEARCHMIND_2_0_SOURCE_OF_TRUTH.md`; track progress in `docs/IMPLEMENTATION_STATUS.md` and measured hosts in `docs/deployment-report.md`.
- V1 Streamlit/pipeline baseline is frozen at git tag `v1-baseline`; keep V1 modules and offline V1 tests green while V2 grows beside them under `backend/`.
- V2 stack target: FastAPI + LiteLLM SDK Router (free-only allowlist, no paid fallback), LangGraph bounded research, PostgreSQL/Neon durable jobs/quotas/checkpoints, REST + SSE (no first-release WebSockets), React/Vite Research Console, thin Cloudflare MCP Worker, Render deployability with a public URL as definition-of-done.
- Prefer Python 3.13 for the backend locally; Python 3.15 failed LiteLLM native builds in this environment.
- LiteLLM Gemini id `gemini/gemini-2.0-flash` returned HTTP 404 (retired); point defaults at the current Flash alias and do not claim a live Gemini pass without a fresh verified call.
- SSRF fetch is a partial in-process IP dial (`backend/app/security/egress_fetch.py` via `tools.scrape_url`): each hop is resolved and dialed on the checked global IP, with Host/SNI kept as the original hostname. R04 stays open; there is no separate egress proxy, and other sockets bypass the helper. Do not document SSRF as closed.
- Local Docker/Postgres is not always available; `FOR UPDATE SKIP LOCKED` lease behavior needs real Postgres and is not proven by SQLite-only paths.
- Live Singapore deploy stack: Neon in `aws-ap-southeast-1`, Render API `https://researchmind-api-sg.onrender.com`, Vercel console `https://researchmind-console.vercel.app` (`sin1`, `VITE_API_BASE` → SG API), Cloudflare MCP Worker `https://researchmind-mcp.jadhavsumit534.workers.dev` (points at SG API).
- Guest research still needs Turnstile keys on Render/Vercel; real LLM runs need provider keys on Render and `USE_MOCK_PROVIDER=false`.
- Static portfolio marketing landing lives under `frontend/landing/` (HTML/CSS/JS, CloudFront background video, Bubbledot + Geist Pixel); React console remains under `frontend/`.
