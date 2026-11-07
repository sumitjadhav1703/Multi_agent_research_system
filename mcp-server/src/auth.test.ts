import { describe, expect, it } from "vitest";

import { parseBearer, unauthorizedResponse } from "./auth";
import { handleWorkerRequest, type Env } from "./http";

const TOKEN = "guest-token-value-ok-20";
const ENV: Env = { RESEARCHMIND_API_BASE: "https://api.example.test" };

describe("bearer rejection", () => {
  it.each([
    null,
    "",
    "Basic abc",
    "Bearer",
    "Bearer ",
    "Bearer short",
    `Bearer ${"a".repeat(201)}`,
    "Bearer guest token with spaces!!",
    `Token ${TOKEN}`,
  ])("rejects %j", (header) => {
    expect(parseBearer(header).ok).toBe(false);
  });

  it("accepts a guest-token shaped bearer", () => {
    const parsed = parseBearer(`Bearer ${TOKEN}`);
    expect(parsed).toEqual({ ok: true, token: TOKEN });
  });

  it("returns 401 without echoing the header", async () => {
    const planted = "planted-secret-token-value";
    const response = await handleWorkerRequest(
      new Request("https://mcp.example.test/mcp", {
        method: "POST",
        headers: { authorization: `Bearer ${planted.slice(0, 8)}` },
      }),
      ENV,
      () => {
        throw new Error("mcp handler should not run");
      },
    );
    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toContain("Bearer");
    const text = await response.text();
    expect(text).not.toContain(planted);
    expect(text).toContain("unauthorized");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("does not call the MCP handler when authorization is missing", async () => {
    let called = false;
    const response = await handleWorkerRequest(new Request("https://mcp.example.test/mcp", { method: "POST" }), ENV, () => {
      called = true;
      return new Response("nope");
    });
    expect(called).toBe(false);
    expect(response.status).toBe(401);
  });

  it("forwards a well-shaped token and leaves OPTIONS unauthenticated", async () => {
    const seen: Array<string | null> = [];
    const ok = await handleWorkerRequest(
      new Request("https://mcp.example.test/mcp", {
        method: "POST",
        headers: { authorization: `bearer ${TOKEN}` },
      }),
      ENV,
      (_request, _env, token) => {
        seen.push(token);
        return new Response("ok", { status: 200 });
      },
    );
    expect(ok.status).toBe(200);
    expect(seen).toEqual([TOKEN]);

    const preflight = await handleWorkerRequest(
      new Request("https://mcp.example.test/mcp", { method: "OPTIONS" }),
      ENV,
      (_request, _env, token) => {
        seen.push(token);
        return new Response(null, { status: 204 });
      },
    );
    expect(preflight.status).toBe(204);
    expect(seen[1]).toBeNull();
  });

  it("serves a tool list without the API origin", async () => {
    const response = await handleWorkerRequest(new Request("https://mcp.example.test/health"), ENV, () => new Response("no"));
    const body = (await response.json()) as { tools: string[] };
    expect(body.tools).toEqual([
      "create_research_run",
      "get_research_run",
      "get_research_report",
      "list_research_sources",
      "get_claim_evidence",
      "get_evaluation_summary",
    ]);
    expect(JSON.stringify(body)).not.toContain("api.example.test");
    const missing = await handleWorkerRequest(new Request("https://mcp.example.test/admin"), ENV, () => new Response("no"));
    expect(missing.status).toBe(404);
  });
});

describe("unauthorized response", () => {
  it("does not include a token challenge parameter", async () => {
    const response = unauthorizedResponse();
    expect(response.headers.get("www-authenticate")).toBe('Bearer realm="researchmind-mcp"');
  });
});
