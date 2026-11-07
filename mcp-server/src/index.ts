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
} satisfies ExportedHandler<Env>;
