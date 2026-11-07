import { describe, expect, it } from "vitest";
import type { ResearchRun, RunEvent } from "../api/types";
import { formatUnknown } from "./format";
import { linkCitations, neutralizeHtml } from "./markdown";
import { mergeEvents, runBanners, workerCards } from "./runView";

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
});
