# ADR 0006 — Remote MCP on a thin Cloudflare Worker

- **Status:** Accepted for Milestone 6 implementation, pending parent review
- **Date:** 2026-11-07
- **Related:** ADR 0001 decision 8, source-of-truth §4, implementation plan Milestone 6

ADR 0001 reserved `0005` for hosting choices at Milestone 7. This record is 0006 so that name stays free.

## Decision

1. **Process boundary.** `mcp-server/` is a stateless Cloudflare Worker using `createMcpHandler` from `agents` 0.33.0 and `McpServer` from `@modelcontextprotocol/server` 2.4.0. The route is `/mcp`. The same handler serves current stateless MCP clients and legacy stateless Streamable HTTP clients. There is no Durable Object, no MCP session, and no copy of the LangGraph research graph.

2. **Tools.** The Worker exposes only `create_research_run`, `get_research_run`, `get_research_report`, `list_research_sources`, `get_claim_evidence`, and `get_evaluation_summary`. Each tool validates its arguments and `fetch`es an existing FastAPI route. New JSON routes under `/api/v1` project the same persisted snapshot the SSE stream already builds. They do not start work.

3. **Authentication.** Clients send `Authorization: Bearer <guest_token>` (RFC 6750). The guest token is the one `POST /api/v1/guest-identities` already issues. The Worker rejects a missing or malformed header with HTTP 401 before it builds a tool result. It forwards a well-shaped header unchanged. FastAPI remains the authority for expiry, ownership, the one-use entitlement, and the global caps. A second identity from Cloudflare OAuth would not own those Postgres rows unless a new account system were added. That system is not part of Milestone 6. OAuth discovery (`OAuthResourceServer` plus an authorization-server Worker) stays the documented upgrade for public MCP clients that cannot set a bearer header. It is not shipped here.

4. **Secrets.** `RESEARCHMIND_API_BASE` is a Wrangler var (an origin). Milestone 6 reads no Worker secret. Future secrets go in with `wrangler secret put` and stay out of source, `wrangler.jsonc`, logs, and the frontend. Guest bearers are per request. They are not stored on the Worker.

5. **Failure and retries.** The Worker does not retry `create_research_run`. A timeout after the API has committed does not roll the job back and does not start a second graph. The client retries with the same `idempotency_key`, and the API returns the existing run. A Worker exception cannot write job rows except through that API.

6. **Edge limits.** Create and read tools have separate in-isolate counters (3 and 20 per 60 seconds per token hash). They are not a global quota. Reads do not consume the one-use entitlement. Evaluation summary is the checked-in “not measured” note. It requires a valid guest token and it does not launch DeepEval.

7. **Deploy.** Milestone 6 stops before `wrangler deploy`. A dry run, when it succeeds, only checks packaging. No `workers.dev` URL is claimed.

## Consequences

- Inspector and other clients that accept a static bearer can call the six tools against a running API. OAuth-only clients cannot, until the authorization server exists.
- An isolate restart clears the edge counters. Two isolates can both forward a create; Postgres still applies the one-use and global gates.
- An external start can still be repeated when the client changes idempotency keys or when the API committed and the client never saw the body and then uses a new key. That limitation already belongs to the API. The Worker does not add a second writer.
