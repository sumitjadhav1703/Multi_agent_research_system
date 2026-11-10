import type { EventsPage, HealthReady, ResearchRun, UsageSnapshot } from "./types";

const API_BASE = readEnv("VITE_API_BASE").replace(/\/$/, "");

export function readEnv(name: "VITE_API_BASE" | "VITE_TURNSTILE_SITE_KEY"): string {
  const value = import.meta.env[name];
  return typeof value === "string" ? value.trim() : "";
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function apiUrl(path: string): string {
  if (/[?&](token|access_token|authorization)=/i.test(path)) {
    throw new Error("Credentials must not be placed in the URL.");
  }
  return `${API_BASE}${path}`;
}

interface RequestOptions {
  method?: string;
  token?: string | null;
  body?: unknown;
  headers?: Record<string, string>;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw new ApiError(0, "network", "The research service did not respond. It may be waking up.");
  }
  if (!response.ok) {
    throw await toError(response);
  }
  return (await response.json()) as T;
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { code?: unknown; message?: unknown };
    const code = typeof body.code === "string" ? body.code : "request_failed";
    const message = typeof body.message === "string" ? body.message : "The request failed.";
    return new ApiError(response.status, code, message);
  } catch {
    return new ApiError(response.status, "request_failed", "The request failed.");
  }
}

export function getReady(): Promise<HealthReady> {
  return fetch(apiUrl("/api/v1/health/ready"), { signal: AbortSignal.timeout(8000) })
    .then(async (response) => (await response.json()) as HealthReady)
    .catch(() => ({ status: "not_ready", database: "unreachable" }));
}

export function createGuest(turnstileToken: string): Promise<{ guest_token: string; token_type: string }> {
  return request("/api/v1/guest-identities", {
    method: "POST",
    body: { turnstile_token: turnstileToken },
  });
}

export function getUsage(token: string): Promise<UsageSnapshot> {
  return request("/api/v1/me/usage", { token });
}

export function createRun(token: string, topic: string, idempotencyKey: string): Promise<ResearchRun> {
  return request("/api/v1/research-runs", {
    method: "POST",
    token,
    body: { topic },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export function getRun(token: string, runId: string): Promise<ResearchRun> {
  return request(`/api/v1/research-runs/${encodeURIComponent(runId)}`, { token });
}

export function getEvents(token: string, runId: string, after = 0): Promise<EventsPage> {
  return request(`/api/v1/research-runs/${encodeURIComponent(runId)}/events?after=${after}`, { token });
}

export function cancelRun(token: string, runId: string): Promise<ResearchRun> {
  return request(`/api/v1/research-runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    token,
  });
}

export function reviewRun(
  token: string,
  runId: string,
  action: "approve" | "revise" | "reject",
  comments: string,
): Promise<ResearchRun> {
  return request(`/api/v1/research-runs/${encodeURIComponent(runId)}/${action}`, {
    method: "POST",
    token,
    body: { comments },
  });
}

export function streamUrl(runId: string): string {
  return apiUrl(`/api/v1/research-runs/${encodeURIComponent(runId)}/events/stream`);
}

