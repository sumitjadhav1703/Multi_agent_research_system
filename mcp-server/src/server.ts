/** Stateless MCP server. Tools only forward to FastAPI. */

import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";

import { executeTool, TOOL_CATALOG, type ToolDeps, type ToolName } from "./tools";

const runId = z.string().uuid().describe("Research run UUID returned by create_research_run.");

export const inputSchemas: Record<ToolName, z.ZodType> = {
  create_research_run: z.object({
    topic: z.string().trim().min(1).max(500).describe("Research topic. 1 to 500 characters."),
    idempotency_key: z
      .string()
      .min(1)
      .max(200)
      .regex(/^[\x21-\x7e]+$/, "Visible ASCII only.")
      .describe("Caller-generated key. Reuse it when retrying the same start."),
  }),
  get_research_run: z.object({ run_id: runId }),
  get_research_report: z.object({ run_id: runId }),
  list_research_sources: z.object({ run_id: runId }),
  get_claim_evidence: z.object({
    run_id: runId,
    claim_id: z
      .string()
      .regex(/^[A-Za-z0-9_-]{1,80}$/).describe("Claim id from the stored run."),
  }),
  get_evaluation_summary: z.object({}),
};

export function buildMcpServer(deps: ToolDeps): McpServer {
  const server = new McpServer({
    name: "researchmind",
    version: "0.1.0",
    description:
      "ResearchMind tools forward to the authenticated API. create_research_run consumes the guest one-use quota and the global caps. Call it only when the user explicitly asks to start research. Read tools do not start a run. This server does not search the web or run the research graph.",
  });

  for (const tool of TOOL_CATALOG) {
    server.registerTool(
      tool.name,
      {
        description: tool.description,
        inputSchema: inputSchemas[tool.name],
        annotations: {
          readOnlyHint: tool.kind === "read",
          destructiveHint: false,
          idempotentHint: tool.name === "create_research_run",
          openWorldHint: tool.name === "create_research_run",
        },
      },
      async (args: unknown) => executeTool(tool.name, args, deps),
    );
  }
  return server;
}
