import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ResearchRun, UsageSnapshot } from "../api/types";
import { GUEST_TOKEN_KEY } from "../auth/token";
import { AppRoutes } from "../App";
import { TokenProvider } from "../auth/token";

const sseCalls: { url: string; headers?: Record<string, string> }[] = [];

const SNAPSHOT = {
  run_id: "run-1",
  wording: "Evidence assessed against stored passages. This is not an absolute fact-check.",
  report: {
    version: 1,
    markdown: "Stored finding cites ev_sq1_1.\n\n<script>alert(1)</script>",
    approval_state: "awaiting_review",
    created_at: "2026-11-07T00:00:00Z",
  },
  sources: [
    {
      source_id: "src_sq1_1",
      url: "https://example.test/transit",
      canonical_url: "https://example.test/transit",
      domain: "example.test",
      title: "Transit note",
      excerpt: "Excerpt",
      extraction_method: "snippet",
      retrieved_at: null,
      content_hash: "abc",
    },
  ],
  passages: [
    { evidence_id: "ev_sq1_1", source_id: "src_sq1_1", subquestion_id: "sq1", quote: "Quoted sentence." },
  ],
  claims: [
    {
      claim_id: "cl1",
      text: "A claim",
      status: "insufficient",
      verification_reason: "No overlap.",
      evidence_ids: ["ev_sq1_1"],
    },
  ],
  usage: {
    llm_calls: null,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    search_calls: null,
    estimated_cost_usd: null,
  },
};

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: (
    url: string,
    options: {
      headers?: Record<string, string>;
      signal?: AbortSignal;
      onopen?: (response: Response) => Promise<void>;
      onmessage?: (message: { event: string; data: string }) => void;
      onerror?: (error: unknown) => void;
    },
  ) =>
    new Promise<void>((resolve) => {
      sseCalls.push({ url, headers: options.headers });
      options.signal?.addEventListener("abort", () => resolve(), { once: true });
      if (String(url).includes("reconnect-me")) {
        options.onerror?.(new Error("drop"));
        return;
      }
      void options
        .onopen?.(new Response(null, { status: 200, headers: { "content-type": "text/event-stream" } }))
        .then(() => {
          options.onmessage?.({ event: "snapshot", data: JSON.stringify(SNAPSHOT) });
        });
    }),
}));

const world: { usage: UsageSnapshot; run: ResearchRun } = {
  usage: {
    identity_scope: "guest",
    one_use_consumed: false,
    one_use_refunded: false,
    run_ids: [] as string[],
    global_max_active_runs: 1,
    global_active_runs: 0,
    global_daily_cap: 3,
    global_daily_starts: 0,
    limits: { max_sources: 6, max_parallel_workers: 2, max_wall_clock_seconds: 180 },
    estimated_cost_usd: null,
    note: "One run per issued guest token, not one verified run per person.",
  },
  run: {
    run_id: "run-1",
    status: "cancelled",
    topic: "Public transit reliability",
    approval_status: null,
    stop_reason: "cancelled",
    created_at: "2026-11-07T00:00:00Z",
    started_at: "2026-11-07T00:00:01Z",
    finished_at: "2026-11-07T00:01:00Z",
    attempts: 1,
    cancel_requested: true,
    provider_work_started: true,
    error_code: "cancelled",
    budgets: {},
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  function Wrap({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <TokenProvider>
          <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
        </TokenProvider>
      </QueryClientProvider>
    );
  }
  return render(<AppRoutes />, { wrapper: Wrap });
}

beforeEach(() => {
  sseCalls.length = 0;
  sessionStorage.clear();
  world.usage.one_use_consumed = false;
  world.usage.run_ids = [];
  world.run.status = "cancelled";
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("token=") || url.includes("authorization=")) return json({ code: "unauthorized", message: "no" }, 401);
    if (url.includes("/health/ready")) {
      return json({ status: "ready", database: "ok", use_mock_provider: true, roles: [], allowlist_size: 1 });
    }
    if (url.includes("/me/usage")) return json(world.usage);
    if (url.includes("/events")) return json({ run_id: "run-1", events: [{ sequence_id: 4, type: "worker.failed", payload: { subquestion_id: "sq1" }, created_at: "2026-11-07T00:00:02Z" }] });
    if (url.endsWith("/research-runs") && init?.method === "POST") {
      const headers = new Headers(init.headers);
      if (!headers.get("Authorization")?.startsWith("Bearer ")) return json({ code: "unauthorized", message: "Guest token is missing or invalid." }, 401);
      return json({ ...world.run, status: "queued", run_id: "run-1", reused: false }, 202);
    }
    if (url.includes("/research-runs/")) return json(world.run);
    return json({ code: "not_found", message: "missing" }, 404);
  }));
});

describe("research console screens", () => {
  it("asks for verification before a guest token exists", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Enter demo" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Verification token" })).toBeInTheDocument();
  });

  it("blocks a second start and offers the saved run", async () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "g".repeat(24));
    world.usage.one_use_consumed = true;
    world.usage.run_ids = ["run-1"];
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Your demo run is used" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start research" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Open run" })).toHaveAttribute("href", "/runs/run-1");
  });

  it("shows a cancelled run from the saved status while the channel connects", async () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "g".repeat(24));
    renderAt("/runs/run-1");
    expect(await screen.findByRole("heading", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Process" })).toBeInTheDocument();
    expect(screen.getByText("Cancelled", { selector: ".pill" })).toBeInTheDocument();
    expect(screen.getByText("Partial result")).toBeInTheDocument();
    expect(screen.getByText("Insufficient evidence")).toBeInTheDocument();
    expect(screen.getByLabelText("Run notices")).toBeInTheDocument();
    expect(await screen.findByText(/live updates|saved on server/i)).toBeInTheDocument();
    expect(sseCalls.at(-1)?.url).not.toMatch(/token|authorization/i);
    expect(sseCalls.at(-1)?.headers?.Authorization).toMatch(/^Bearer /);
  });

  it("keeps the saved status visible when the channel drops", async () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "g".repeat(24));
    world.run = { ...world.run, status: "queued", stop_reason: null, finished_at: null, cancel_requested: false };
    renderAt("/runs/reconnect-me");
    expect(await screen.findByRole("heading", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Process" })).toBeInTheDocument();
    expect(screen.getByText("Queued", { selector: ".pill" })).toBeInTheDocument();
  });

  it("sanitizes the stored report and shows unknown cost on the usage screen", async () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "g".repeat(24));
    world.run = { ...world.run, status: "review_required" };
    renderAt("/runs/run-1/report");
    expect(await screen.findByRole("heading", { name: "Answer" })).toBeInTheDocument();
    expect(await screen.findByText(/Stored finding cites/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByRole("link", { name: "ev_sq1_1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Critics" })).toBeInTheDocument();
  });

  it("shows unknown cost instead of a zero estimate", async () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "g".repeat(24));
    world.usage.run_ids = ["run-1"];
    renderAt("/usage");
    expect(await screen.findByText("Estimated cost (USD)")).toBeInTheDocument();
    expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
  });

  it("does not offer a guest benchmark or invent an accuracy figure", async () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "g".repeat(24));
    renderAt("/evaluation");
    expect(await screen.findByRole("heading", { name: "No benchmark yet" })).toBeInTheDocument();
    expect(screen.getAllByText("not measured").length).toBeGreaterThan(3);
    expect(screen.queryByRole("button", { name: /benchmark/i })).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("starts a run with headers rather than a query token", async () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "g".repeat(24));
    const user = userEvent.setup();
    renderAt("/");
    const box = await screen.findByRole("textbox", { name: "Research question" });
    await user.type(box, "Public transit reliability");
    await user.click(screen.getByRole("button", { name: "Start research" }));
    const fetchMock = vi.mocked(fetch);
    const post = fetchMock.mock.calls.find((call) => {
      const init = call[1] as RequestInit | undefined;
      return init?.method === "POST" && String(call[0]).includes("/research-runs");
    });
    expect(post).toBeTruthy();
    expect(String(post?.[0])).not.toMatch(/token|authorization/i);
    const headers = new Headers((post?.[1] as RequestInit).headers);
    expect(headers.get("Authorization")).toMatch(/^Bearer /);
    expect(headers.get("Idempotency-Key")).toBeTruthy();
  });
});
