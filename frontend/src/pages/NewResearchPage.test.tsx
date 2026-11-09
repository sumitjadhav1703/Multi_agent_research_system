import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRun, getUsage } from "../api/client";
import type { ResearchRun, UsageSnapshot } from "../api/types";
import { GUEST_TOKEN_KEY, TokenProvider } from "../auth/token";
import { NewResearchPage } from "./NewResearchPage";

vi.mock("../api/client", () => ({
  createRun: vi.fn(),
  getUsage: vi.fn(),
}));

const usage: UsageSnapshot = {
  identity_scope: "guest",
  one_use_consumed: false,
  one_use_refunded: false,
  run_ids: [],
  global_max_active_runs: 4,
  global_active_runs: 0,
  global_daily_cap: 20,
  global_daily_starts: 0,
  limits: {},
  estimated_cost_usd: null,
  note: "One run left",
};

function queued(topic: string): ResearchRun {
  return {
    run_id: "run-2",
    status: "queued",
    topic,
    approval_status: null,
    stop_reason: null,
    created_at: "2026-11-10T00:00:00Z",
    started_at: null,
    finished_at: null,
    attempts: 1,
    cancel_requested: false,
    provider_work_started: false,
    error_code: null,
    budgets: {},
  };
}

function renderPage() {
  sessionStorage.setItem(GUEST_TOKEN_KEY, "guest-token");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <TokenProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </TokenProvider>
    </QueryClientProvider>
  );
  return render(<NewResearchPage />, { wrapper });
}

describe("NewResearchPage idempotency", () => {
  beforeEach(() => {
    vi.mocked(getUsage).mockResolvedValue(usage);
    vi.mocked(createRun).mockReset();
  });

  it("keeps the idempotency key when the topic changes while start is pending", async () => {
    const user = userEvent.setup();
    let rejectStart: (error: Error) => void = () => undefined;
    vi.mocked(createRun).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectStart = reject;
        }),
    );
    renderPage();
    await screen.findByText("One run left");
    const topic = screen.getByRole("textbox", { name: "Research question" });
    await user.type(topic, "First question");
    await user.click(screen.getByRole("button", { name: "Start research" }));
    expect(await screen.findByRole("button", { name: "Starting…" })).toBeDisabled();

    await user.clear(topic);
    await user.type(topic, "Edited while starting");
    await act(async () => {
      rejectStart(new Error("still starting"));
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("still starting");

    vi.mocked(createRun).mockResolvedValueOnce(queued("Edited while starting"));
    await user.click(screen.getByRole("button", { name: "Start research" }));

    const calls = vi.mocked(createRun).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0]?.[1]).toBe("First question");
    expect(calls[1]?.[1]).toBe("Edited while starting");
    expect(calls[1]?.[2]).toBe(calls[0]?.[2]);
  });

  it("rotates the idempotency key when the topic changes while idle", async () => {
    const user = userEvent.setup();
    vi.mocked(createRun).mockRejectedValueOnce(new Error("nope"));
    renderPage();
    await screen.findByText("One run left");
    const topic = screen.getByRole("textbox", { name: "Research question" });
    await user.type(topic, "Alpha");
    await user.click(screen.getByRole("button", { name: "Start research" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");

    await user.type(topic, " beta");
    vi.mocked(createRun).mockResolvedValueOnce(queued("Alpha beta"));
    await user.click(screen.getByRole("button", { name: "Start research" }));

    const keys = vi.mocked(createRun).mock.calls.map((call) => call[2]);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBeTruthy();
    expect(keys[1]).not.toBe(keys[0]);
  });
});
