import { describe, expect, it } from "vitest";
import type { ResearchRun, RunEvent } from "../api/types";
import { formatUnknown } from "./format";
import { linkCitations, neutralizeHtml } from "./markdown";
import { mergeEvents, nextActionHint, runBanners, sourcesSeenCount, workerCards } from "./runView";

const run = (status: string, extra: Partial<ResearchRun> = {}): ResearchRun => ({
  run_id: "run-1",
  status,
  topic: "Transit",
  approval_status: null,
  stop_reason: null,
  created_at: "2026-11-07T00:00:00Z",
  started_at: null,
  finished_at: null,
  attempts: 1,
  cancel_requested: false,
  provider_work_started: false,
  error_code: null,
  budgets: {},
  ...extra,
});

const event = (sequence_id: number, type: string, payload: Record<string, unknown> = {}): RunEvent => ({
  sequence_id,
  type,
  payload,
  created_at: "2026-11-07T00:00:00Z",
});

describe("run view", () => {
  it("keeps unknown usage unknown", () => {
    expect(formatUnknown(null)).toBe("unknown");
    expect(formatUnknown(0)).toBe("0");
  });

  it("dedupes events by sequence", () => {
    const merged = mergeEvents([event(1, "run.queued")], [event(1, "run.queued"), event(2, "planner.started")]);
    expect(merged.map((item) => item.sequence_id)).toEqual([1, 2]);
  });

  it("describes reconnect, quota states, failure, and insufficient evidence", () => {
    const titles = (status: string, events: RunEvent[] = [], extra: Partial<ResearchRun> = {}) =>
      runBanners({
        run: run(status, extra),
        events,
        snapshot: {
          run_id: "run-1",
          wording: "Evidence assessed against stored passages. This is not an absolute fact-check.",
          report: null,
          sources: [],
          passages: [],
          claims: [{ claim_id: "cl1", text: "A claim", status: "insufficient", verification_reason: null, evidence_ids: [] }],
          usage: {
            llm_calls: null,
            prompt_tokens: null,
            completion_tokens: null,
            total_tokens: null,
            search_calls: null,
            estimated_cost_usd: null,
          },
        },
        connection: status === "queued" ? "reconnecting" : "closed",
      }).map((banner) => banner.title);

    expect(titles("queued")).toContain("Reconnecting");
    expect(titles("queued")).toContain("Queued");
    expect(titles("running")).toContain("Running");
    expect(titles("review_required")).toContain("Review required");
    expect(titles("completed", [], { approval_status: "rejected", stop_reason: "human_rejected" })).toContain("Rejected");
    expect(titles("failed", [], { error_code: "graph_error" })).toContain("Failed");
    expect(titles("cancelled")).toContain("Cancelled");
    expect(titles("expired")).toContain("Expired");
    expect(titles("completed", [event(3, "worker.failed")])).toContain("Partial result");
    expect(titles("completed")).toContain("Insufficient evidence");
    expect(titles("completed")).not.toContain("Reconnecting");

    const provisionalBanners = runBanners({
      run: run("completed"),
      events: [],
      snapshot: {
        run_id: "run-1",
        wording: "Evidence assessed against stored passages. This is not an absolute fact-check.",
        report: {
          version: 1,
          markdown: "# T\n\n## Provisional answer (unverified)\n\nQueues help resume work.\n\n## Insufficient evidence\n\nNo evidence-backed claim could be assessed.\n",
          approval_state: "awaiting_review",
          created_at: "2026-11-09T00:00:00Z",
        },
        sources: [],
        passages: [],
        claims: [{ claim_id: "cl1", text: "A claim", status: "insufficient", verification_reason: null, evidence_ids: [] }],
        usage: {
          llm_calls: null,
          prompt_tokens: null,
          completion_tokens: null,
          total_tokens: null,
          search_calls: null,
          estimated_cost_usd: null,
        },
      },
      connection: "closed",
    });
    const insufficient = provisionalBanners.find((banner) => banner.id === "insufficient");
    expect(insufficient?.detail).toContain("provisional answer");

    const gapOnlyBanners = runBanners({
      run: run("completed"),
      events: [],
      snapshot: {
        run_id: "run-1",
        wording: "Evidence assessed against stored passages. This is not an absolute fact-check.",
        report: {
          version: 1,
          markdown:
            "# T\n\n## Insufficient evidence\n\nNo evidence-backed claim could be assessed. Any provisional text is unverified.\n",
          approval_state: "awaiting_review",
          created_at: "2026-11-09T00:00:00Z",
        },
        sources: [],
        passages: [],
        claims: [{ claim_id: "cl1", text: "A claim", status: "insufficient", verification_reason: null, evidence_ids: [] }],
        usage: {
          llm_calls: null,
          prompt_tokens: null,
          completion_tokens: null,
          total_tokens: null,
          search_calls: null,
          estimated_cost_usd: null,
        },
      },
      connection: "closed",
    });
    const gapOnly = gapOnlyBanners.find((banner) => banner.id === "insufficient");
    expect(gapOnly?.detail).toContain("Stored passages do not support");
    expect(gapOnly?.detail).not.toContain("provisional answer is shown");
  });

  it("does not invent a provider name", () => {
    const cards = workerCards([
      event(1, "worker.started", { subquestion_ids: ["sq1"] }),
      event(2, "worker.completed", { subquestion_id: "sq1", sources: 2 }),
    ]);
    expect(cards[0]).toMatchObject({ provider: "unknown", sources: 2, state: "completed" });
  });

  it("turns citation ids into links and neutralizes tags", () => {
    expect(neutralizeHtml("See <script>alert(1)</script>")).not.toContain("<script>");
    expect(linkCitations("See ev_sq1_1.", ["ev_sq1_1"])).toContain("](#cite-ev_sq1_1)");
  });

  it("humanizes next-action copy by surface and answer presence", () => {
    expect(nextActionHint(run("completed"), true, "live")).toContain("open Report");
    expect(nextActionHint(run("completed"), true, "report")).toContain("full write-up below");
    expect(nextActionHint(run("completed"), true, "evidence")).toContain("passages below");
    expect(nextActionHint(run("completed"), false, "evidence")).toContain("No stored answer");
  });

  it("counts sources from snapshot or discovered/extracted events", () => {
    const events = [
      event(1, "source.discovered", { source_id: "src_a", extraction_method: "html" }),
      event(2, "source.extracted", { source_id: "src_a", extraction_method: "html" }),
    ];
    expect(sourcesSeenCount(events, null)).toBe(1);
    expect(sourcesSeenCount([], 3)).toBe(3);
    expect(sourcesSeenCount(events, 2)).toBe(2);
  });
});
