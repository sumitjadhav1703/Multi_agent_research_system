/* Local UX verification only — seeds guest token + fetch fixtures before the SPA boots. */
(() => {
  const tokenKey = "researchmind.guestToken";
  sessionStorage.setItem(tokenKey, "g".repeat(24));
  const SNAPSHOT = {
    run_id: "run-1",
    wording: "Evidence assessed against stored passages. This is not an absolute fact-check.",
    report: {
      version: 1,
      markdown:
        "# Verified Claim Ledger Report\n\nStored finding cites [ev_sq1_1](#cite-ev_sq1_1).\n\nThe transit network improved reliability in published city reports.\n\nYear-over-year on-time performance rose in the published city note used for this run.\n\nClaims that go beyond the stored passage stay marked insufficient rather than invented.\n\nUse Evidence to read the exact quote that supports each citation id.",
      approval_state: "approved",
      created_at: "2026-11-07T00:00:00Z",
    },
    sources: [
      {
        source_id: "src_sq1_1",
        url: "https://example.test/transit",
        canonical_url: "https://example.test/transit",
        domain: "example.test",
        title: "Transit note",
        excerpt: "City reliability improved year over year.",
        extraction_method: "html",
        retrieved_at: "2026-11-07T00:00:10Z",
        content_hash: "abc",
      },
    ],
    passages: [
      {
        evidence_id: "ev_sq1_1",
        source_id: "src_sq1_1",
        subquestion_id: "sq1",
        quote: "City reliability improved year over year.",
      },
    ],
    claims: [
      {
        claim_id: "cl1",
        text: "Reliability improved in published city reports.",
        status: "insufficient",
        verification_reason: "Passage overlap is thin.",
        evidence_ids: ["ev_sq1_1"],
      },
    ],
    usage: {
      llm_calls: 5,
      prompt_tokens: 148,
      completion_tokens: 616,
      total_tokens: 764,
      search_calls: 4,
      estimated_cost_usd: null,
    },
  };
  const RUN = {
    run_id: "run-1",
    status: "completed",
    topic: "Public transit reliability",
    approval_status: "approved",
    stop_reason: "approved",
    created_at: "2026-11-07T00:00:00Z",
    started_at: "2026-11-07T00:00:01Z",
    finished_at: "2026-11-07T00:03:06Z",
    attempts: 1,
    cancel_requested: false,
    provider_work_started: true,
    error_code: null,
    budgets: {},
  };
  const USAGE = {
    identity_scope: "guest",
    one_use_consumed: true,
    one_use_refunded: false,
    run_ids: ["run-1"],
    global_max_active_runs: 1,
    global_active_runs: 0,
    global_daily_cap: 3,
    global_daily_starts: 1,
    limits: { max_sources: 6, max_parallel_workers: 2, max_wall_clock_seconds: 180 },
    estimated_cost_usd: null,
    note: "One run per issued guest token, not one verified run per person.",
  };
  const EVENTS = [
    { sequence_id: 1, type: "planner.completed", payload: {}, created_at: "2026-11-07T00:00:02Z" },
    { sequence_id: 2, type: "worker.completed", payload: { subquestion_id: "sq1", sources: 2 }, created_at: "2026-11-07T00:00:03Z" },
    {
      sequence_id: 3,
      type: "source.discovered",
      payload: {
        source_id: "src_sq1_1",
        url: "https://example.test/transit",
        extraction_method: "html",
      },
      created_at: "2026-11-07T00:00:04Z",
    },
    {
      sequence_id: 4,
      type: "source.extracted",
      payload: { source_id: "src_sq1_1", extraction_method: "html" },
      created_at: "2026-11-07T00:00:04Z",
    },
    { sequence_id: 5, type: "evidence.extracted", payload: {}, created_at: "2026-11-07T00:00:05Z" },
    { sequence_id: 6, type: "claim.verified", payload: {}, created_at: "2026-11-07T00:00:06Z" },
    { sequence_id: 7, type: "writer.completed", payload: {}, created_at: "2026-11-07T00:00:07Z" },
    { sequence_id: 8, type: "run.completed", payload: {}, created_at: "2026-11-07T00:00:08Z" },
  ];
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  const sse = (chunks) => {
    const enc = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(enc.encode(chunk));
        controller.close();
      },
    });
    return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
  };
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input);
    if (url.includes("/health/ready")) {
      return json({ status: "ready", database: "ok", use_mock_provider: true, roles: [], allowlist_size: 1 });
    }
    if (url.includes("/me/usage")) return json(USAGE);
    if (url.includes("/events/stream")) {
      return sse([
        `event: snapshot\ndata: ${JSON.stringify(SNAPSHOT)}\n\n`,
        `event: stream.closed\ndata: {}\n\n`,
      ]);
    }
    if (url.includes("/events")) return json({ run_id: "run-1", events: EVENTS });
    if (url.includes("/research-runs/")) return json(RUN);
    return orig(input, init);
  };
})();
