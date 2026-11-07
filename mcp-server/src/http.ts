/** HTTP gate in front of the stateless MCP handler. */

import { parseBearer, unauthorizedResponse } from "./auth";
import { TOOL_CATALOG } from "./tools";

/**
 * Request env for the worker. `worker-configuration.d.ts` also declares a global
 * `Env` whose var type is the literal in wrangler.jsonc. This one stays a string
 * so a deployed origin can differ from the local default.
 */
export interface Env {
  RESEARCHMIND_API_BASE?: string;
}

export type McpCaller = (request: Request, env: Env, token: string | null) => Promise<Response> | Response;

export async function handleWorkerRequest(request: Request, env: Env, callMcp: McpCaller): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
    return Response.json(
      {
        service: "researchmind-mcp",
        transport: "streamable-http",
        endpoint: "/mcp",
        tools: TOOL_CATALOG.map((tool) => tool.name),
      },
      { headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } },
    );
  }
  if (url.pathname !== "/mcp") {
    return Response.json(
      { code: "not_found", message: "MCP endpoint is /mcp." },
      { status: 404, headers: { "cache-control": "no-store" } },
    );
  }
  if (request.method === "OPTIONS") return callMcp(request, env, null);
  const parsed = parseBearer(request.headers.get("Authorization"));
  if (!parsed.ok) return unauthorizedResponse();
  return callMcp(request, env, parsed.token);
}
