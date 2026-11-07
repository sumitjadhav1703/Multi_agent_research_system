import { describe, expect, it, vi } from "vitest";
import { apiUrl, createRun, streamUrl } from "./client";

describe("api client", () => {
  it("refuses credentials in the URL", () => {
    expect(() => apiUrl("/api/v1/research-runs?token=secret")).toThrow(/URL/);
    expect(streamUrl("run-1")).not.toMatch(/token|authorization/i);
  });

  it("sends the bearer token and idempotency key as headers", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ run_id: "run-1", status: "queued" }), { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await createRun("guest-token-value", "Transit", "idem-1");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).not.toMatch(/token|authorization|idem/i);
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer guest-token-value");
    expect(headers.get("Idempotency-Key")).toBe("idem-1");
    vi.unstubAllGlobals();
  });
});
