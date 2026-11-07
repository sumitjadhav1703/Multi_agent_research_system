import { describe, expect, it, vi } from "vitest";

import { redactValue, resolveApiBase } from "./forward";
import { EdgeLimiter } from "./limits";
import { executeTool, type ToolDeps } from "./tools";

const TOKEN = "guest-token-value-ok-20";
const RUN_ID = "11111111-1111-4111-8111-111111111111";

function deps(fetchImpl: typeof fetch, limiter = new EdgeLimiter()): ToolDeps {
  return {
    apiBase: "https://api.example.test",
    token: TOKEN,
    fetchImpl,
    limiter,
    now: () => 1_000,
    createTimeoutMs: 50,
    readTimeoutMs: 50,
  };
}

function sent(fetchImpl: typeof fetch): { url: string; init: RequestInit }[] {
  return vi.mocked(fetchImpl).mock.calls.map((call) => ({
    url: String(call[0]),
    init: (call[1] ?? {}) as RequestInit,
  }));
}

function header(init: RequestInit, name: string): string | null {
  const headers = new Headers(init.headers);
  return headers.get(name);
}

describe("API base", () => {
  it("allows https origins and local http only", () => {
    expect(resolveApiBase("https://api.example.test")).toBe("https://api.example.test");
    expect(resolveApiBase("https://api.example.test/")).toBe("https://api.example.test");
    expect(resolveApiBase("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000");
    expect(resolveApiBase("http://localhost:8000/")).toBe("http://localhost:8000");
    expect(resolveApiBase("http://api.example.test")).toBeNull();
    expect(resolveApiBase("https://user:secret@api.example.test")).toBeNull();
    expect(resolveApiBase("https://api.example.test/hidden")).toBeNull();
    expect(resolveApiBase("https://api.example.test/?q=1")).toBeNull();
    expect(resolveApiBase(undefined)).toBeNull();
  });
});

describe("forwarder", () => {
  it("posts a create with the guest bearer and idempotency key only", async () => {
    const fetchImpl = vi.fn(async () => Response.json({ run_id: RUN_ID, status: "queued", reused: false }, { status: 202 }));
    const result = await executeTool(
      "create_research_run",
      { topic: "  Transit reliability  ", idempotency_key: "key-1", max_model_calls: 99 },
      deps(fetchImpl),
    );
    expect(result.isError).toBe(false);
    expect(JSON.parse(result.content[0].text)).toMatchObject({ run_id: RUN_ID, status: "queued" });
    const request = sent(fetchImpl)[0];
    expect(request?.url).toBe("https://api.example.test/api/v1/research-runs");
    expect(request?.init.method).toBe("POST");
    expect(header(request!.init, "authorization")).toBe(`Bearer ${TOKEN}`);
    expect(header(request!.init, "idempotency-key")).toBe("key-1");
    expect(request?.init.body).toBe(JSON.stringify({ topic: "Transit reliability" }));
    expect(request?.url).not.toContain(TOKEN);
  });

  it("does not fetch when create input is invalid", async () => {
    const fetchImpl = vi.fn();
    const result = await executeTool("create_research_run", { topic: "   ", idempotency_key: "key-1" }, deps(fetchImpl));
    expect(result.isError).toBe(true);
    expect(JSON.parse(result.content[0].text).code).toBe("invalid_input");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("maps quota exhaustion and does not retry", async () => {
    const fetchImpl = vi.fn(async () =>
      Response.json({ code: "quota_consumed", message: "This guest identity has already used its one research run." }, { status: 409 }),
    );
    const result = await executeTool(
      "create_research_run",
      { topic: "Transit", idempotency_key: "key-2" },
      deps(fetchImpl),
    );
    expect(result.isError).toBe(true);
    expect(JSON.parse(result.content[0].text)).toMatchObject({ code: "quota_consumed" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("forwards owner-scoped reads and drops secret-shaped fields", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.endsWith("/sources")) {
        return Response.json({
          run_id: RUN_ID,
          sources: [{ source_id: "src1", title: "Note", excerpt: "x".repeat(800), guest_token: TOKEN }],
        });
      }
      return Response.json({ run_id: RUN_ID, status: "completed", authorization: "nope", error_detail: "hidden" });
    });
    const run = await executeTool("get_research_run", { run_id: RUN_ID }, deps(fetchImpl));
    const sources = await executeTool("list_research_sources", { run_id: RUN_ID }, deps(fetchImpl));
    const runBody = JSON.parse(run.content[0].text);
    expect(runBody.status).toBe("completed");
    expect(runBody.authorization).toBeUndefined();
    expect(runBody.error_detail).toBeUndefined();
    const sourceBody = JSON.parse(sources.content[0].text);
    expect(sourceBody.sources[0].guest_token).toBeUndefined();
    expect(sourceBody.sources[0].excerpt.endsWith("…")).toBe(true);
    expect(sourceBody.truncated).toBe(true);
    expect(sources.content[0].text).not.toContain(TOKEN);
    const request = sent(fetchImpl)[1];
    expect(request?.init.method).toBe("GET");
    expect(request?.url).toBe(`https://api.example.test/api/v1/research-runs/${RUN_ID}/sources`);
  });

  it("passes through an API 401 and a not-found without the bearer", async () => {
    const fetchImpl = vi.fn(async () =>
      Response.json({ code: "unauthorized", message: `rejected ${TOKEN}` }, { status: 401 }),
    );
    const denied = await executeTool("get_research_run", { run_id: RUN_ID }, deps(fetchImpl));
    expect(JSON.parse(denied.content[0].text).message).not.toContain(TOKEN);
    expect(JSON.parse(denied.content[0].text).code).toBe("unauthorized");

    fetchImpl.mockResolvedValueOnce(Response.json({ code: "run_not_found", message: "Run not found." }, { status: 404 }));
    const missing = await executeTool("get_research_report", { run_id: RUN_ID }, deps(fetchImpl));
    expect(JSON.parse(missing.content[0].text).code).toBe("run_not_found");
  });

  it("stops at the edge limiter before a create reaches the API", async () => {
    const fetchImpl = vi.fn(async () => Response.json({ run_id: RUN_ID }, { status: 202 }));
    const limiter = new EdgeLimiter(1, 2, 60_000);
    const shared = deps(fetchImpl, limiter);
    const first = await executeTool("create_research_run", { topic: "Transit", idempotency_key: "once" }, shared);
    const second = await executeTool("create_research_run", { topic: "Transit", idempotency_key: "once" }, shared);
    expect(first.isError).toBe(false);
    expect(JSON.parse(second.content[0].text).code).toBe("edge_rate_limited");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("uses a separate read bucket", async () => {
    const fetchImpl = vi.fn(async () => Response.json({ published: true, measured: false, judge: { scores: null } }));
    const limiter = new EdgeLimiter(1, 1, 60_000);
    const shared = deps(fetchImpl, limiter);
    await executeTool("create_research_run", { topic: "Transit", idempotency_key: "once" }, shared);
    const summary = await executeTool("get_evaluation_summary", {}, shared);
    expect(summary.isError).toBe(false);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const blocked = await executeTool("get_evaluation_summary", {}, shared);
    expect(JSON.parse(blocked.content[0].text).code).toBe("edge_rate_limited");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("returns timeout and provider failure without a second attempt", async () => {
    const hanging = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        signal?.addEventListener("abort", () => {
          const error = new Error("timed out");
          error.name = "TimeoutError";
          reject(error);
        });
      });
    });
    const timed = await executeTool(
      "get_claim_evidence",
      { run_id: RUN_ID, claim_id: "cl1" },
      { ...deps(hanging as typeof fetch), readTimeoutMs: 15 },
    );
    expect(JSON.parse(timed.content[0].text).code).toBe("upstream_timeout");
    expect(hanging).toHaveBeenCalledTimes(1);

    const failed = vi.fn(async () => Response.json({ code: "database_unavailable", message: "Database is unavailable." }, { status: 503 }));
    const down = await executeTool("get_research_run", { run_id: RUN_ID }, deps(failed));
    expect(JSON.parse(down.content[0].text).code).toBe("database_unavailable");
    expect(failed).toHaveBeenCalledTimes(1);
  });

  it("rejects a bad run id and a cleartext API base before fetch", async () => {
    const fetchImpl = vi.fn();
    const badId = await executeTool("list_research_sources", { run_id: "../admin" }, deps(fetchImpl));
    expect(JSON.parse(badId.content[0].text).code).toBe("invalid_input");
    const badBase = await executeTool(
      "get_research_run",
      { run_id: RUN_ID },
      { ...deps(fetchImpl), apiBase: "http://evil.example" },
    );
    expect(JSON.parse(badBase.content[0].text).code).toBe("mcp_misconfigured");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("redacts a bearer that an upstream body echoes", () => {
    expect(redactValue({ note: `see ${TOKEN}`, nested: [TOKEN] }, TOKEN)).toEqual({
      note: "see [redacted]",
      nested: ["[redacted]"],
    });
  });

  it("forwards two creates and lets the API decide the race", async () => {
    const fetchImpl = vi.fn(async () => Response.json({ run_id: RUN_ID, reused: false }, { status: 202 }));
    const limiter = new EdgeLimiter(5, 5, 60_000);
    await Promise.all([
      executeTool("create_research_run", { topic: "Transit", idempotency_key: "race" }, deps(fetchImpl, limiter)),
      executeTool("create_research_run", { topic: "Transit", idempotency_key: "race" }, deps(fetchImpl, limiter)),
    ]);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    for (const request of sent(fetchImpl)) {
      expect(header(request.init, "authorization")).toBe(`Bearer ${TOKEN}`);
      expect(header(request.init, "idempotency-key")).toBe("race");
    }
  });
});
