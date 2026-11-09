import { describe, expect, it } from "vitest";
import type { ResearchRun } from "../api/types";
import { runBanners } from "./runView";

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

describe("run view discovery", () => {
  it("mentions provider_failure when a failed run has no error_code", () => {
    const banners = runBanners({
      run: run("failed", { error_code: null, stop_reason: "provider_failure" }),
      events: [],
      snapshot: null,
      connection: "closed",
    });
    const failed = banners.find((banner) => banner.id === "failed");

    expect(failed?.detail ?? "").toContain("provider_failure");
  });
});
