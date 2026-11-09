import { describe, expect, it } from "vitest";
import type { UsageSnapshot } from "../api/types";
import { usageFiguresFromSnapshot } from "./UsagePage";

const base: UsageSnapshot = {
  identity_scope: "guest",
  one_use_consumed: false,
  one_use_refunded: false,
  run_ids: [],
  global_max_active_runs: 1,
  global_active_runs: 0,
  global_daily_cap: 3,
  global_daily_starts: 0,
  limits: {},
  estimated_cost_usd: null,
  note: "note",
};

describe("usageFiguresFromSnapshot", () => {
  it("maps ledger totals and keeps null cost", () => {
    const figures = usageFiguresFromSnapshot({
      ...base,
      llm_calls: 4,
      prompt_tokens: 10,
      completion_tokens: 5,
      total_tokens: 15,
      search_calls: 2,
      estimated_cost_usd: null,
    });
    expect(figures).toEqual({
      llm_calls: 4,
      prompt_tokens: 10,
      completion_tokens: 5,
      total_tokens: 15,
      search_calls: 2,
      estimated_cost_usd: null,
    });
  });

  it("treats missing ledger fields as null, not zero", () => {
    expect(usageFiguresFromSnapshot(base)).toEqual({
      llm_calls: null,
      prompt_tokens: null,
      completion_tokens: null,
      total_tokens: null,
      search_calls: null,
      estimated_cost_usd: null,
    });
  });
});
