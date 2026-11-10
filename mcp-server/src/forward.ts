/** HTTPS forwarder. The Worker does not retry a create call. */

import { bearerShapeOk } from "./auth";
import { MAX_UPSTREAM_BYTES } from "./limits";

// "token" only as a whole key segment, so prompt_tokens/total_tokens counts pass.
const SECRET_KEY = /(^|[_-])(token|secret|authorization|password|cookie)($|[_-])|api[_-]?key|error_detail/i;

export type ForwardRequest = {
  apiBase: string;
  token: string;
  method: "GET" | "POST";
  path: string;
  body?: unknown;
  idempotencyKey?: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
};

export type ForwardSuccess = {
  ok: true;
  status: number;
  body: unknown;
};

export type ForwardFailure = {
  ok: false;
  status: number;
  code: string;
  message: string;
};

export type ForwardResult = ForwardSuccess | ForwardFailure;

export function resolveApiBase(raw: string | undefined): string | null {
  if (!raw || raw.length > 300) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.username || url.password || url.search || url.hash) return null;
  if (url.pathname !== "/" && url.pathname !== "") return null;
  const host = url.hostname.toLowerCase();
  const local = host === "localhost" || host === "127.0.0.1";
  if (url.protocol === "https:") return url.origin;
  if (url.protocol === "http:" && local) return url.origin;
  return null;
}

export async function forwardApi(input: ForwardRequest): Promise<ForwardResult> {
  const origin = resolveApiBase(input.apiBase);
  if (!origin) {
    return {
      ok: false,
      status: 500,
      code: "mcp_misconfigured",
      message: "RESEARCHMIND_API_BASE is missing or not an allowed origin.",
    };
  }
  if (!bearerShapeOk(input.token)) {
    return {
      ok: false,
      status: 401,
      code: "unauthorized",
      message: "Bearer token is missing or invalid.",
    };
  }
  if (!input.path.startsWith("/api/v1/")) {
    return {
      ok: false,
      status: 500,
      code: "mcp_misconfigured",
      message: "The worker refused a path outside the research API.",
    };
  }

  const headers = new Headers();
  headers.set("authorization", `Bearer ${input.token}`);
  headers.set("accept", "application/json");
  headers.set("user-agent", "researchmind-mcp/0.1");
  if (input.body !== undefined) headers.set("content-type", "application/json");
  if (input.idempotencyKey) headers.set("idempotency-key", input.idempotencyKey);

  const fetchImpl = input.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(`${origin}${input.path}`, {
      method: input.method,
      headers,
      body: input.body === undefined ? undefined : JSON.stringify(input.body),
      signal: AbortSignal.timeout(input.timeoutMs),
      cache: "no-store",
      redirect: "error",
    });
  } catch (error) {
    if (isTimeout(error)) {
      return {
        ok: false,
        status: 504,
        code: "upstream_timeout",
        message: "The research API did not answer before the worker timeout. Retry create with the same idempotency key.",
      };
    }
    return {
      ok: false,
      status: 502,
      code: "upstream_unavailable",
      message: "The research API could not be reached.",
    };
  }

  const declared = Number(response.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > MAX_UPSTREAM_BYTES) {
    await response.body?.cancel();
    return {
      ok: false,
      status: 502,
      code: "response_too_large",
      message: "The research API response exceeded the worker size cap.",
    };
  }

  const read = await readCapped(response);
  if (!read.ok) return read.failure;
  const parsed = parseJson(read.text);
  if (!response.ok) {
    const code = stringField(parsed, "code") ?? "upstream_error";
    const message = stringField(parsed, "message") ?? "The research API returned an error.";
    return {
      ok: false,
      status: response.status,
      code: clip(code, 80),
      message: clip(redactText(message, input.token), 300),
    };
  }
  if (parsed === undefined) {
    return {
      ok: false,
      status: 502,
      code: "upstream_invalid",
      message: "The research API returned a response that was not JSON.",
    };
  }
  return { ok: true, status: response.status, body: redactValue(parsed, input.token) };
}

function isTimeout(error: unknown): boolean {
  return error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError");
}

async function readCapped(
  response: Response,
): Promise<{ ok: true; text: string } | { ok: false; failure: ForwardFailure }> {
  const reader = response.body?.getReader();
  if (!reader) return { ok: true, text: "" };
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const step = await reader.read();
    if (step.done) break;
    total += step.value.byteLength;
    if (total > MAX_UPSTREAM_BYTES) {
      await reader.cancel();
      return {
        ok: false,
        failure: {
          ok: false,
          status: 502,
          code: "response_too_large",
          message: "The research API response exceeded the worker size cap.",
        },
      };
    }
    chunks.push(step.value);
  }
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, text: new TextDecoder().decode(merged) };
}

function parseJson(text: string): unknown {
  if (!text.trim()) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function stringField(value: unknown, key: string): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const found = (value as Record<string, unknown>)[key];
  return typeof found === "string" && found.trim() ? found : undefined;
}

function clip(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max)}…`;
}

export function redactText(value: string, token: string): string {
  if (!token) return value;
  return value.split(token).join("[redacted]");
}

export function redactValue(value: unknown, token: string): unknown {
  if (typeof value === "string") return redactText(value, token);
  if (Array.isArray(value)) return value.map((item) => redactValue(item, token));
  if (!value || typeof value !== "object") return value;
  const output: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (SECRET_KEY.test(key)) continue;
    output[key] = redactValue(item, token);
  }
  return output;
}
