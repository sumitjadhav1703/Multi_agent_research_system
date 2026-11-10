/** Best-effort per-isolate caps. Postgres quotas remain the durable gate. */

export const CREATE_EDGE_LIMIT = 3;
export const READ_EDGE_LIMIT = 20;
export const EDGE_WINDOW_MS = 60_000;
export const CREATE_TIMEOUT_MS = 20_000;
export const READ_TIMEOUT_MS = 10_000;
export const MAX_TOOL_CHARS = 12_000;
export const MAX_UPSTREAM_BYTES = 256_000;
export const MAX_MARKDOWN_CHARS = 8_000;
export const MAX_TEXT_CHARS = 500;

export type LimitKind = "create" | "read";

type Bucket = { stamps: number[]; seen: number };

export class EdgeLimiter {
  private readonly buckets = new Map<string, Bucket>();

  constructor(
    private readonly createLimit = CREATE_EDGE_LIMIT,
    private readonly readLimit = READ_EDGE_LIMIT,
    private readonly windowMs = EDGE_WINDOW_MS,
    private readonly maxBuckets = 256,
  ) {}

  allow(kind: LimitKind, key: string, now: number): boolean {
    const id = `${kind}:${key}`;
    const windowStart = now - this.windowMs;
    const current = this.buckets.get(id);
    const stamps = (current?.stamps ?? []).filter((stamp) => stamp > windowStart);
    const limit = kind === "create" ? this.createLimit : this.readLimit;
    if (stamps.length >= limit) {
      this.buckets.set(id, { stamps, seen: now });
      return false;
    }
    stamps.push(now);
    this.buckets.set(id, { stamps, seen: now });
    this.trim();
    return true;
  }

  private trim(): void {
    if (this.buckets.size <= this.maxBuckets) return;
    const ranked = [...this.buckets.entries()].sort((left, right) => left[1].seen - right[1].seen);
    const extra = this.buckets.size - this.maxBuckets;
    for (const [key] of ranked.slice(0, extra)) {
      this.buckets.delete(key);
    }
  }
}

export const edgeLimiter = new EdgeLimiter();

export async function tokenKey(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return [...new Uint8Array(digest)].slice(0, 8).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
