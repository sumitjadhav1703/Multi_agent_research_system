import { createMcpHandler } from "agents/mcp/server";
import { expect, it } from "vitest";

import { buildMcpServer } from "./server";
import { TOOL_CATALOG } from "./tools";

const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;

it("registers only the approved tools", () => {
  const server = buildMcpServer({
    apiBase: "https://api.example.test",
    token: "guest-token-value-ok-20",
  });
  const registered = Object.keys(
    (server as unknown as { _registeredTools: Record<string, unknown> })._registeredTools,
  ).sort();
  expect(registered).toEqual(TOOL_CATALOG.map((tool) => tool.name).sort());
});

async function rpcResult(response: Response): Promise<{ result?: { serverInfo?: { name?: string }; tools?: { name: string }[] } }> {
  const text = await response.text();
  const payload = text.trim().startsWith("{")
    ? text
    : text
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .filter((line) => line.startsWith("{"))
        .at(-1);
  if (!payload) throw new Error(`No JSON-RPC body in ${text.slice(0, 180)}`);
  return JSON.parse(payload) as { result?: { serverInfo?: { name?: string }; tools?: { name: string }[] } };
}

it("lists those tools over stateless Streamable HTTP", async () => {
  const token = "guest-token-value-ok-20";
  const handler = createMcpHandler(() => buildMcpServer({ apiBase: "https://api.example.test", token }), { route: "/mcp" });
  const headers = {
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    authorization: `Bearer ${token}`,
  };
  const init = await handler(
    new Request("https://mcp.example.test/mcp", {
      method: "POST",
      headers,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2025-06-18",
          capabilities: {},
          clientInfo: { name: "unit", version: "0" },
        },
      }),
    }),
    {},
    ctx,
  );
  expect(init.status).toBe(200);
  const opened = await rpcResult(init);
  expect(opened.result?.serverInfo?.name).toBe("researchmind");

  const listed = await handler(
    new Request("https://mcp.example.test/mcp", {
      method: "POST",
      headers,
      body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
    }),
    {},
    ctx,
  );
  expect(listed.status).toBe(200);
  const body = await rpcResult(listed);
  expect(body.result?.tools?.map((tool) => tool.name).sort()).toEqual(TOOL_CATALOG.map((tool) => tool.name).sort());
});
