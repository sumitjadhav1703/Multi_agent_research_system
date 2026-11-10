/** Cloudflare Worker entry. Streamable HTTP MCP, no research graph. */

import { createMcpHandler } from "agents/mcp/server";

import { handleWorkerRequest, type Env } from "./http";
import { buildMcpServer } from "./server";

export type { Env };

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    return handleWorkerRequest(request, env, (incoming, workerEnv, token) => {
      const handler = createMcpHandler(
        () =>
          buildMcpServer({
            apiBase: workerEnv.RESEARCHMIND_API_BASE ?? "",
            token: token ?? "",
          }),
        { route: "/mcp" },
      );
      return handler(incoming, workerEnv, ctx);
    });
  },
  // Keep-awake: ping the API so the free-tier host does not sleep.
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      fetch(`${env.RESEARCHMIND_API_BASE}/api/v1/health/live`, { signal: AbortSignal.timeout(60_000) }).then(
        (response) => console.log(`keepalive status ${response.status}`),
        (error: unknown) => console.log(`keepalive failed ${error instanceof Error ? error.name : "error"}`),
      ),
    );
  },
} satisfies ExportedHandler<Env>;
