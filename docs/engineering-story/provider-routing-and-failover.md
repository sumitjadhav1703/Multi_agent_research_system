# Provider routing and failover

**ADR:** [`../ADR/0002-provider-routing.md`](../ADR/0002-provider-routing.md)  
**Code:** `backend/app/providers/*`, `backend/app/core/config.py`  
**External doc check:** LiteLLM Router/Proxy ([docs.litellm.ai](https://docs.litellm.ai/)), 2026-11-08  

Provider free-tier quotas, RPM, and model catalogs change frequently. Treat tables below as **research notes**, not contractual guarantees. Re-verify before a scored demo.

---

## LiteLLM SDK Router vs Proxy

| | SDK Router (chosen) | LiteLLM Proxy |
|---|---|---|
| Process | In-process inside FastAPI | Separate gateway service |
| Ops | Config via env / Settings | YAML + proxy deploy |
| RAM on Render Free | Shares 512 MB with API + consumer | Competes as second service |
| Fallbacks | `Router(..., fallbacks=[...])` | Proxy `router_settings.fallbacks` |
| ResearchMind choice | **SDK Router** | Rejected for first release |

ResearchMind sets underlying SDK `max_retries=0` and `LITELLM_NUM_RETRIES=0` by default, with **at most one** configured fallback alias per role, to avoid retry storms and duplicate billed work after timeouts.

---

## Approved free allowlist (code defaults)

From `DEFAULT_FREE_ALLOWLIST` in `backend/app/core/config.py`:

| Model ID | Role default use | Notes |
|---|---|---|
| `groq/openai/gpt-oss-120b` | planner / writer primary, verifier fallback, eval_judge | Live JSON probe pass 2026-11-11 (1.2 s) |
| `groq/openai/gpt-oss-20b` | researcher primary | Live pass; separate Groq rate-limit bucket from 120b. Reasoning model: needs the 2000-token budget. |
| `openrouter/nvidia/nemotron-3.5-super-vl:free` | verifier primary | Live JSON probe pass 2026-11-11 (2.2 s). OpenRouter `:free`: 20 req/min, 50 req/day (1,000 after a one-time $10 purchase). |
| `nvidia_nim/meta/llama-3.3-70b-instruct` | planner / researcher / writer fallback | NVIDIA NIM free tier (~40 req/min); needs `NVIDIA_NIM_API_KEY` |
| `meta/muse-spark-1.3-contributor` | paid last resort for every role (owner-approved, `META_LAST_RESORT_ENABLED=true`) | Live pass 2026-11-11; runs only after a role's free primary and fallback both fail |
| `mock/free-model` | in the code default allowlist; omitted from `render.yaml`'s production list | `USE_MOCK_PROVIDER=true` |

Dropped 2026-11-11: `gemini/*` (503s and timeouts; free tier cut to ~20–100 req/day) and `mistral/*` (429s on the free Experiment tier). `openrouter/meta-llama/llama-3.2-3b-instruct:free` no longer exists on OpenRouter.

`ALLOW_PAID_MODELS=true` or paid markers (`gpt-4`, `claude-sonnet-4`, …) → **fail closed at startup**.

---

## Role routing (defaults)

| Role | Alias | Primary | Fallback |
|---|---|---|---|
| planner | `rm-planner` | groq/openai/gpt-oss-120b | nvidia_nim/meta/llama-3.3-70b-instruct |
| researcher | `rm-researcher` | groq/openai/gpt-oss-20b | nvidia_nim/meta/llama-3.3-70b-instruct |
| verifier | `rm-verifier` | openrouter/nvidia/nemotron-3.5-super-vl:free (a different model family checks the extractor) | groq/openai/gpt-oss-120b |
| writer | `rm-writer` | groq/openai/gpt-oss-120b | nvidia_nim/meta/llama-3.3-70b-instruct |
| eval_judge | `rm-eval-judge` | groq/openai/gpt-oss-120b | none |

`eval_judge` is only the in-app alias; the offline DeepEval judge uses `meta/muse-spark-1.3-contributor` (`evals/__init__.py`). Fallbacks must also be on the allowlist. When a role's free primary and fallback both fail, the owner-approved paid Meta Muse last resort runs; if it also fails, stop safely and preserve completed stages/events. No other paid model is ever used.

---

## Provider investigation notes (verify before demo)

Research date: **2026-11-08**. Official dashboards remain authoritative.

### Groq
- Used heavily in V1 and V2 defaults.  
- Fast inference; free-tier rate limits are real (V1 exposes `PipelinePaused` on 429).  
- Tool-calling / structured-output for the default model: **NOT VERIFIED** in V2 matrix → graph avoids requiring JSON mode.

### Google Gemini and Mistral (removed 2026-11-11)
- Gemini returned 503s and timeouts in live runs, and its free tier was cut to roughly 20–100 requests/day.
- Mistral's free Experiment tier returned 429 rate limits.
- Both left claims unverified, so both were removed from the defaults, `render.yaml` and the allowlist.

### NVIDIA NIM
- Free hosted endpoints at build.nvidia.com, OpenAI-compatible, ~40 requests/min; LiteLLM prefix `nvidia_nim/`.

### OpenRouter
- Free-suffixed models still require an OpenRouter key and obey OpenRouter rate/credit rules.  
- Not a blank check for unlimited inference.

---

## Reliability controls

| Control | Implementation | Status |
|---|---|---|
| Model aliases | `ROLE_ALIASES` | IMPLEMENTED |
| Capability validation | Startup allowlist + paid markers; runtime JSON parse | PARTIAL (no full tool/json-mode matrix) |
| Retry policy | Default 0 router retries | IMPLEMENTED |
| Timeout | `LITELLM_REQUEST_TIMEOUT` default 45s | IMPLEMENTED |
| Rate-limit handling | Error mapping in `ModelClient`; job may fail/pause path | IMPLEMENTED |
| Circuit breakers | Rely on LiteLLM Router deployment health where configured; app keeps fallbacks minimal | PARTIAL |
| Fallback conditions | Only configured allowlisted hop; an empty provider reply also falls back to the role fallback model | IMPLEMENTED · VERIFIED offline |
| Meta last resort | One post-chain call to `META_LAST_RESORT_MODEL` only when `META_LAST_RESORT_ENABLED=true`, a Meta key is set, and the model is allowlisted; off in `render.yaml` | IMPLEMENTED (optional) |
| Token tracking | Usage ledger; null stays null; tokens are counted after failed calls | IMPLEMENTED · VERIFIED |
| Cost estimates | List-price when measured; null/unknown when not | IMPLEMENTED |
| Failure recovery | Persist events; no paid escape hatch | IMPLEMENTED |

### Hard rules (SoT)

1. No automatic paid-provider fallback.  
2. Only explicitly approved models.  
3. Quota exhaustion must not trigger uncontrolled retries.  
4. Failed provider must not silently switch to unapproved model.  
5. If all approved providers fail → stop; keep completed work.  
6. Avoid blindly retrying timed-out generations (may already be billed).  
7. Test tool-calling / structured-output before relying on them as fallback requirements.

---

## Live evidence on record

| Check | Result |
|---|---|
| Mock router CI | VERIFIED (unit tests) |
| M2 live text smoke (128 tokens) | Groq planner/researcher/writer **pass**; Gemini 2.0-flash verifier/eval **fail** (`all_providers_unavailable` / 404) |
| `gemini/gemini-flash-latest` live | **NOT VERIFIED** after alias change |
| Hosted research-run token/cost | **NOT MEASURED** |

---

## Operational recommendation

Before any interview demo that depends on verifier/judge roles:

1. Run `backend/scripts/live_text_smoke.py` with current aliases.  
2. Confirm Tavily + primary Groq path.  
3. Record date, model IDs, and pass/fail in `docs/deployment-report.md`.  
4. If a provider fails, point the role at a verified allowlisted alternative **explicitly** through env vars. No code change is needed.
