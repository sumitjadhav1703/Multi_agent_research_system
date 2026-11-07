# ADR 0003 — Bounded LangGraph evidence graph

- **Status:** Accepted for Milestone 2 implementation, pending parent review
- **Date:** 2026-11-07
- **Related:** ADR 0001, ADR 0002, source-of-truth §5, implementation plan Milestone 2

## Decision

Implement the research workflow as one LangGraph `StateGraph` in `backend/app/graph/` with these bounds:

- Planner output is clamped to 3 subquestions.
- Fan-out uses `Send`, and each scheduling step emits at most 2 workers.
- Workers return isolated results. A merge node dedupes by canonical URL and content hash.
- Search and HTML fetch go through a port. The default adapter uses the same Tavily search shape as V1 and calls V1 `validate_public_url` before `scrape_url`.
- Retrieved text is untrusted data inside explicit delimiters. It cannot select tools. The worker tool set is the fixed search/fetch port.
- Claim status `supported` or `contradictory` is kept only when the evidence id resolves to a stored passage. `supported` also requires term overlap with that quote. Deterministic citation checks run again before human review.
- Evidence gaps get one follow-up search, then the report continues with a visible gap section.
- Human review uses `interrupt`. Approve, reject, or one revise are accepted. A second revise stops.
- The compiled graph uses `InMemorySaver` unless a Postgres checkpointer is supplied. Durable checkpoints are ADR 0004. `build_checkpointer("postgres")` fails closed until `open_postgres_checkpointer` holds the connection.
- Graph events are appended for a later SSE log and also written with LangGraph's custom stream writer. There is no SSE route in this milestone.
- PDF bytes are not parsed. A PDF URL is recorded as snippet-only.
- The graph asks models for JSON text and parses it locally. It does not require provider JSON mode or tool calling, because those capabilities are not yet verified for every allowlisted model.

## Consequences

- Control-flow ceilings are testable without a network or provider quota.
- A paused review does not survive a process restart, and a provider call interrupted mid-node can run again.
- Reports say "evidence assessed." They do not claim an absolute fact-check.
- `gemini/gemini-2.0-flash` returned HTTP 404 during the Milestone 2 text smoke. Milestone 3 points new defaults at `gemini/gemini-flash-latest` and leaves the retired id allowlisted. That alias was not live-tested.
