/** Tool handlers. Each one forwards. None of them run a research graph. */

import { bearerShapeOk } from "./auth";
import { forwardApi, type ForwardResult } from "./forward";
import {
  CREATE_TIMEOUT_MS,
  EdgeLimiter,
  MAX_MARKDOWN_CHARS,
  MAX_TEXT_CHARS,
  MAX_TOOL_CHARS,
  READ_TIMEOUT_MS,
  edgeLimiter,
  tokenKey,
} from "./limits";

export const TOOL_CATALOG = [
  {
    name: "create_research_run",
    kind: "create",
    description:
      "Start one bounded ResearchMind job for an explicit user request. This consumes the guest one-use quota and the API global caps. Repeat the same idempotency_key to reuse the accepted job instead of starting another.",
  },
  {
    name: "get_research_run",
    kind: "read",
    description: "Read status and stage fields for a run owned by this guest token.",
  },
  {
    name: "get_research_report",
    kind: "read",
    description: "Read the stored report markdown and short citation metadata for an owned run. A null report means none is stored yet.",
  },
  {
    name: "list_research_sources",
    kind: "read",
    description: "List stored sources for an owned run. Excerpts are shortened.",
  },
  {
    name: "get_claim_evidence",
    kind: "read",
    description: "Read one owned claim and the stored passages linked to it. This does not perform a new fact check.",
  },
  {
    name: "get_evaluation_summary",
    kind: "read",
    description:
      "Read the manually published evaluation note. Judge scores are null when they were not measured. This does not start a benchmark.",
  },
] as const;

export type ToolName = (typeof TOOL_CATALOG)[number]["name"];

export type ToolDeps = {
  apiBase: string;
  token: string;
  fetchImpl?: typeof fetch;
  now?: () => number;
  limiter?: EdgeLimiter;
  createTimeoutMs?: number;
  readTimeoutMs?: number;
};

export type ToolContent = {
  content: [{ type: "text"; text: string }];
  isError?: boolean;
};

export async function executeTool(name: string, args: unknown, deps: ToolDeps): Promise<ToolContent> {
  const catalog = TOOL_CATALOG.find((tool) => tool.name === name);
  if (!catalog) return toolError("unknown_tool", "That tool is not exposed.");
  if (!bearerShapeOk(deps.token)) return toolError("unauthorized", "Bearer token is missing or invalid.");

  const record = asRecord(args);

  const limiter = deps.limiter ?? edgeLimiter;
  const key = await tokenKey(deps.token);
  const now = (deps.now ?? Date.now)();
  if (!limiter.allow(catalog.kind, key, now)) {
    return toolError(
      "edge_rate_limited",
      catalog.kind === "create"
        ? "Create calls are temporarily limited at the worker. The API quota was not consumed."
        : "Read calls are temporarily limited at the worker.",
    );
  }

  const timeoutMs = catalog.kind === "create" ? (deps.createTimeoutMs ?? CREATE_TIMEOUT_MS) : (deps.readTimeoutMs ?? READ_TIMEOUT_MS);
  const result = await dispatch(catalog.name, record, deps, timeoutMs);
  if (!result.ok) return toolError(result.code, result.message);
  const bounded = boundPayload(result.body);
  return {
    content: [{ type: "text", text: bounded.text }],
    isError: false,
  };
}

function markTruncated(value: unknown): unknown {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return { ...(value as Record<string, unknown>), truncated: true };
  }
  return { truncated: true, value };
}

async function dispatch(name: ToolName, args: Record<string, unknown>, deps: ToolDeps, timeoutMs: number): Promise<ForwardResult> {
  const runId = typeof args.run_id === "string" ? args.run_id : "";
  switch (name) {
    case "create_research_run":
      return forwardApi({
        apiBase: deps.apiBase,
        token: deps.token,
        method: "POST",
        path: "/api/v1/research-runs",
        body: { topic: String(args.topic).trim() },
        idempotencyKey: String(args.idempotency_key).trim(),
        timeoutMs,
        fetchImpl: deps.fetchImpl,
      });
    case "get_research_run":
      return forwardApi({
        apiBase: deps.apiBase,
        token: deps.token,
        method: "GET",
        path: `/api/v1/research-runs/${encodeURIComponent(runId)}`,
        timeoutMs,
        fetchImpl: deps.fetchImpl,
      });
    case "get_research_report":
      return forwardApi({
        apiBase: deps.apiBase,
        token: deps.token,
        method: "GET",
        path: `/api/v1/research-runs/${encodeURIComponent(runId)}/report`,
        timeoutMs,
        fetchImpl: deps.fetchImpl,
      });
    case "list_research_sources":
      return forwardApi({
        apiBase: deps.apiBase,
        token: deps.token,
        method: "GET",
        path: `/api/v1/research-runs/${encodeURIComponent(runId)}/sources`,
        timeoutMs,
        fetchImpl: deps.fetchImpl,
      });
    case "get_claim_evidence":
      return forwardApi({
        apiBase: deps.apiBase,
        token: deps.token,
        method: "GET",
        path: `/api/v1/research-runs/${encodeURIComponent(runId)}/claims/${encodeURIComponent(String(args.claim_id))}/evidence`,
        timeoutMs,
        fetchImpl: deps.fetchImpl,
      });
    case "get_evaluation_summary":
      return forwardApi({
        apiBase: deps.apiBase,
        token: deps.token,
        method: "GET",
        path: "/api/v1/evaluation/summary",
        timeoutMs,
        fetchImpl: deps.fetchImpl,
      });
  }
}

function asRecord(args: unknown): Record<string, unknown> {
  if (!args || typeof args !== "object" || Array.isArray(args)) return {};
  return args as Record<string, unknown>;
}

function toolError(code: string, message: string): ToolContent {
  return {
    isError: true,
    content: [{ type: "text", text: JSON.stringify({ code, message }) }],
  };
}

export function boundPayload(value: unknown): { text: string; truncated: boolean } {
  const clipped = clipValue(value, false);
  const first = clipped.truncated ? markTruncated(clipped.value) : clipped.value;
  let text = JSON.stringify(first);
  if (text.length <= MAX_TOOL_CHARS) return { text, truncated: clipped.truncated };
  const tighter = clipValue(value, true);
  text = JSON.stringify(markTruncated(tighter.value));
  if (text.length <= MAX_TOOL_CHARS) return { text, truncated: true };
  return {
    text: JSON.stringify({
      truncated: true,
      code: "response_truncated",
      message: "The tool result was shortened to fit the worker response cap.",
    }),
    truncated: true,
  };
}

function clipValue(value: unknown, tight: boolean): { value: unknown; truncated: boolean } {
  const markdownMax = tight ? 1_000 : MAX_MARKDOWN_CHARS;
  const textMax = tight ? 120 : MAX_TEXT_CHARS;
  let truncated = false;
  const walk = (item: unknown, key: string): unknown => {
    if (typeof item === "string") {
      const max = key === "markdown" ? markdownMax : textMax;
      if (item.length > max) {
        truncated = true;
        return `${item.slice(0, max)}…`;
      }
      return item;
    }
    if (Array.isArray(item)) return item.map((entry) => walk(entry, key));
    if (!item || typeof item !== "object") return item;
    const output: Record<string, unknown> = {};
    for (const [childKey, child] of Object.entries(item as Record<string, unknown>)) {
      output[childKey] = walk(child, childKey);
    }
    return output;
  };
  return { value: walk(value, ""), truncated };
}
