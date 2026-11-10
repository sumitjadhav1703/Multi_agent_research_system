import type {
  ArtifactSnapshot,
  ConnectionState,
  ResearchRun,
  RunEvent,
  UsageFigures,
} from "../api/types";
import { EMPTY_USAGE } from "../api/types";

export const ACTIVE_STATUSES = new Set(["queued", "running", "review_required"]);
export const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "expired", "rejected"]);

export type StageState = "pending" | "active" | "done" | "failed";
export type BannerTone = "info" | "warning" | "danger" | "ok";

export interface StageView {
  id: string;
  label: string;
  blurb: string;
  state: StageState;
}

export interface Banner {
  id: string;
  tone: BannerTone;
  title: string;
  detail: string;
}

export interface WorkerCard {
  subquestionId: string;
  state: "started" | "completed" | "failed";
  sources: number | null;
  provider: string;
  error: string | null;
}

export interface DiscoveredSource {
  sourceId: string;
  url: string;
  extractionMethod: string;
}

const STAGES: {
  id: string;
  label: string;
  blurb: string;
  start: string[];
  done: string[];
  fail?: string[];
}[] = [
  {
    id: "plan",
    label: "Plan",
    blurb: "Shape the question",
    start: ["planner.started"],
    done: ["planner.completed"],
  },
  {
    id: "workers",
    label: "Workers",
    blurb: "Parallel research",
    start: ["worker.started"],
    done: ["worker.completed"],
    fail: ["worker.failed"],
  },
  {
    id: "sources",
    label: "Sources",
    blurb: "Gather pages",
    start: ["source.discovered"],
    done: [], // finishes when a later stage starts
  },
  {
    id: "evidence",
    label: "Evidence",
    blurb: "Extract passages",
    start: ["worker.completed"],
    done: ["evidence.extracted"],
  },
  {
    id: "verify",
    label: "Verify",
    blurb: "Check claims",
    start: ["evidence.extracted"],
    done: [], // finishes when the writer starts
  },
  {
    id: "report",
    label: "Report",
    blurb: "Write the answer",
    start: ["writer.started"],
    done: ["writer.completed"],
  },
  {
    id: "review",
    label: "Review",
    blurb: "Human gate",
    start: ["review.awaiting", "review.requested"],
    done: ["review.resumed", "run.completed"],
  },
];

export function statusLabel(status: string): string {
  switch (status) {
    case "queued":
      return "Queued";
    case "running":
      return "Running";
    case "review_required":
      return "Review required";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    case "expired":
      return "Expired";
    case "rejected":
      return "Rejected";
    default:
      return status || "Unknown";
  }
}

export function maxSequence(events: readonly RunEvent[]): number {
  return events.reduce((max, event) => Math.max(max, event.sequence_id), 0);
}

export function mergeEvents(current: readonly RunEvent[], incoming: readonly RunEvent[]): RunEvent[] {
  const map = new Map<number, RunEvent>();
  for (const event of current) map.set(event.sequence_id, event);
  for (const event of incoming) {
    if (Number.isFinite(event.sequence_id)) map.set(event.sequence_id, event);
  }
  return [...map.values()].sort((left, right) => left.sequence_id - right.sequence_id);
}

export function stageStates(events: readonly RunEvent[], status: string): StageView[] {
  const types = new Set(events.map((event) => event.type));
  return STAGES.map((stage, index) => {
    const failed = (stage.fail ?? []).some((type) => types.has(type));
    const laterStarted = STAGES.slice(index + 1).some((next) =>
      [...next.start, ...next.done].some((type) => types.has(type)),
    );
    const finished = stage.done.some((type) => types.has(type)) || laterStarted;
    let state: StageState = "pending";
    if (finished) state = "done";
    else if (failed) state = "failed";
    else if (stage.start.some((type) => types.has(type))) state = "active";
    if (stage.id === "review" && status === "review_required") state = "active";
    return { id: stage.id, label: stage.label, blurb: stage.blurb, state };
  });
}

/** Revisions already consumed (backend allows one). */
export function revisionsUsed(events: readonly RunEvent[]): number {
  return events.filter((event) => event.type === "review.resumed" && event.payload.action === "revise").length;
}

export function workerCards(events: readonly RunEvent[]): WorkerCard[] {
  const cards = new Map<string, WorkerCard>();
  for (const event of events) {
    if (event.type === "worker.started") {
      const ids = Array.isArray(event.payload.subquestion_ids) ? event.payload.subquestion_ids : [];
      for (const id of ids) {
        const key = String(id);
        if (!cards.has(key)) {
          cards.set(key, {
            subquestionId: key,
            state: "started",
            sources: null,
            provider: "unknown",
            error: null,
          });
        }
      }
    }
    if (event.type === "worker.completed" || event.type === "worker.failed") {
      const key = String(event.payload.subquestion_id ?? "unknown");
      const current = cards.get(key) ?? {
        subquestionId: key,
        state: "started" as const,
        sources: null,
        provider: "unknown",
        error: null,
      };
      current.state = event.type === "worker.failed" ? "failed" : "completed";
      if (typeof event.payload.sources === "number") current.sources = event.payload.sources;
      if (typeof event.payload.provider === "string" && event.payload.provider) {
        current.provider = event.payload.provider;
      }
      if (typeof event.payload.error === "string") current.error = event.payload.error;
      cards.set(key, current);
    }
  }
  return [...cards.values()];
}

export function discoveredSources(events: readonly RunEvent[]): DiscoveredSource[] {
  const sources = new Map<string, DiscoveredSource>();
  for (const event of events) {
    if (event.type !== "source.discovered" && event.type !== "source.extracted") continue;
    const sourceId = String(event.payload.source_id ?? "");
    if (!sourceId) continue;
    const prior = sources.get(sourceId);
    sources.set(sourceId, {
      sourceId,
      url: typeof event.payload.url === "string" ? event.payload.url : (prior?.url ?? ""),
      extractionMethod:
        typeof event.payload.extraction_method === "string"
          ? event.payload.extraction_method
          : (prior?.extractionMethod ?? "unknown"),
    });
  }
  return [...sources.values()];
}

/** Prefer durable snapshot count; fall back to unique source ids in progress events. */
export function sourcesSeenCount(
  events: readonly RunEvent[],
  snapshotSourceCount: number | null | undefined = null,
): number {
  const fromEvents = discoveredSources(events).length;
  const fromSnapshot = typeof snapshotSourceCount === "number" ? snapshotSourceCount : 0;
  return Math.max(fromEvents, fromSnapshot);
}

export function usageFromEvents(events: readonly RunEvent[]): UsageFigures {
  const usage: UsageFigures = { ...EMPTY_USAGE };
  for (const event of events) {
    if (event.type !== "usage.updated") continue;
    assignUsage(usage, event.payload);
  }
  return usage;
}

function assignUsage(target: UsageFigures, payload: Record<string, unknown>) {
  const keys = ["llm_calls", "prompt_tokens", "completion_tokens", "total_tokens", "search_calls"] as const;
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "number") target[key] = value;
    if (value === null) target[key] = null;
  }
  if (typeof payload.estimated_cost_usd === "number" || typeof payload.estimated_cost_usd === "string") {
    target.estimated_cost_usd = payload.estimated_cost_usd;
  }
  if (payload.estimated_cost_usd === null) target.estimated_cost_usd = null;
}

export function isRejected(run: Pick<ResearchRun, "approval_status" | "stop_reason">): boolean {
  if (run.approval_status === "rejected") return true;
  // revision_limit is only a warning now: the run returns to review, it is not rejected.
  return run.stop_reason === "human_rejected" || run.stop_reason === "invalid_review_action";
}

export function insufficientEvidence(events: readonly RunEvent[], snapshot: ArtifactSnapshot | null): boolean {
  if (snapshot && snapshot.claims.length > 0) {
    return snapshot.claims.every((claim) => claim.status === "insufficient");
  }
  if (events.some((event) => event.type === "warning" && event.payload.code === "evidence_retry")) return true;
  const counted = events.some((event) => event.type === "claim.verified" && event.payload.count === 0);
  if (counted) return true;
  const verified = events.filter(
    (event) => event.type === "claim.verified" && typeof event.payload.status === "string",
  );
  return verified.length > 0 && verified.every((event) => event.payload.status === "insufficient");
}

export function providerNotice(events: readonly RunEvent[]): string | null {
  for (const event of events) {
    const code = typeof event.payload.code === "string" ? event.payload.code : "";
    if (event.type === "warning" && /rate|fallback/i.test(code)) return code;
    if (event.payload.fallback === true) return "provider fallback";
  }
  return null;
}

export function runBanners(input: {
  run: ResearchRun;
  events: readonly RunEvent[];
  snapshot: ArtifactSnapshot | null;
  connection: ConnectionState;
}): Banner[] {
  const banners: Banner[] = [];
  if (input.connection === "reconnecting") {
    banners.push({
      id: "reconnect",
      tone: "warning",
      title: "Reconnecting",
      detail: "The progress channel is down. The status shown is the saved run from the server.",
    });
  }
  if (input.run.cancel_requested && !TERMINAL_STATUSES.has(input.run.status)) {
    banners.push({
      id: "cancel-requested",
      tone: "warning",
      title: "Cancellation requested",
      detail: "The run will stop at the next safe point. The one-use demo run stays consumed.",
    });
  }
  banners.push(statusBanner(input.run, revisionsUsed(input.events) > 0));
  if (input.events.some((event) => event.type === "worker.failed")) {
    banners.push({
      id: "partial",
      tone: "warning",
      title: "Partial result",
      detail:
        "At least one research worker failed. Saved sources stay visible. A failed worker is not a verified result.",
    });
  }
  if (insufficientEvidence(input.events, input.snapshot)) {
    const hasProvisional = Boolean(
      input.snapshot?.report?.markdown &&
        /^##\s*Provisional answer/im.test(input.snapshot.report.markdown),
    );
    banners.push({
      id: "insufficient",
      tone: "warning",
      title: "Insufficient evidence",
      detail: hasProvisional
        ? "A provisional answer is shown below. It is not evidence-backed. This is not an absolute fact-check."
        : "Stored passages do not support a stronger claim. This is not an absolute fact-check.",
    });
  }
  const notice = providerNotice(input.events);
  if (notice) {
    banners.push({
      id: "provider",
      tone: "warning",
      title: "Provider warning",
      detail: notice,
    });
  }
  return banners;
}

/** Notices for the top-right cluster — drop statuses already covered by the status pill. */
export function noticeBanners(input: Parameters<typeof runBanners>[0]): Banner[] {
  return runBanners(input).filter((banner) => banner.id !== "queued" && banner.id !== "running");
}

function failureDetail(run: ResearchRun): string {
  const errorCode = run.error_code?.trim() ?? "";
  if (errorCode) return `Error code: ${errorCode}.`;
  const stopReason = run.stop_reason?.trim() ?? "";
  if (stopReason) return `Stop reason: ${stopReason}.`;
  return "The run failed before a report was approved.";
}

function statusBanner(run: ResearchRun, revisionUsed: boolean): Banner {
  if (run.status === "queued") {
    return {
      id: "queued",
      tone: "info",
      title: "Queued",
      detail: "The run is saved and waiting for the worker. Refreshing keeps this status.",
    };
  }
  if (run.status === "running") {
    return {
      id: "running",
      tone: "info",
      title: "Running",
      detail: "Research is in progress. The saved status is refreshed from the server.",
    };
  }
  if (run.status === "review_required") {
    return {
      id: "review",
      tone: "warning",
      title: "Review required",
      detail: revisionUsed
        ? "Approve or reject. The one allowed revision was already used."
        : "Approve, request one revision, or reject. A second revision is not offered.",
    };
  }
  if (run.status === "expired") {
    return {
      id: "expired",
      tone: "danger",
      title: "Expired",
      detail: run.error_code ? `Stop code: ${run.error_code}.` : "The run passed its time limit.",
    };
  }
  if (run.status === "cancelled") {
    return {
      id: "cancelled",
      tone: "warning",
      title: "Cancelled",
      detail: "This demo run was cancelled. The one-use allowance stays consumed.",
    };
  }
  if (run.status === "failed") {
    return {
      id: "failed",
      tone: "danger",
      title: "Failed",
      detail: failureDetail(run),
    };
  }
  if (run.status === "rejected" || isRejected(run)) {
    return {
      id: "rejected",
      tone: "danger",
      title: "Rejected",
      detail: run.stop_reason ? `Stop reason: ${run.stop_reason}.` : "The report was rejected.",
    };
  }
  if (run.approval_status === "approved" || run.stop_reason === "approved") {
    return {
      id: "approved",
      tone: "ok",
      title: "Approved",
      detail: "The saved report was approved. Evaluation not measured for this run.",
    };
  }
  return {
    id: "completed",
    tone: "ok",
    title: "Completed",
    detail: run.stop_reason ? `Stop reason: ${run.stop_reason}.` : "The run finished and was saved.",
  };
}

export function summarizeEvent(event: RunEvent): string {
  const bits: string[] = [];
  for (const [key, value] of Object.entries(event.payload)) {
    if (key === "event_id" || key === "report" || key === "claims") continue;
    if (value == null) continue;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      bits.push(`${key}: ${value}`);
    }
  }
  const text = bits.join(" · ");
  if (!text) return "No extra detail.";
  return text.length > 300 ? `${text.slice(0, 300)}…` : text;
}

export type HintSurface = "live" | "report" | "evidence" | "generic";

export function nextActionHint(
  run: ResearchRun,
  hasAnswer: boolean,
  surface: HintSurface = "generic",
): string | null {
  switch (run.status) {
    case "queued":
      return "Queued. The process rail will move when a worker picks this run up.";
    case "running":
      return "Research is in progress. Watch the process rail for the active step.";
    case "review_required":
      return surface === "report"
        ? "Waiting for your review — approve, revise, or reject below."
        : "Waiting for your review — open Report to approve, revise, or reject.";
    case "completed":
      if (!hasAnswer) return "Run finished. No stored answer body for this run.";
      if (surface === "report") return "Answer ready — full write-up below.";
      if (surface === "evidence") return "Answer ready — passages below show what it can claim.";
      return "Answer ready — open Report for the full write-up.";
    case "failed":
      return "This run failed. Check Activity for the stop reason.";
    case "cancelled":
      return "This run was cancelled.";
    case "expired":
      return "This run expired before it finished.";
    case "rejected":
      return "This run was rejected.";
    default:
      return null;
  }
}

export function answerMarkdown(
  snapshot: ArtifactSnapshot | null,
  events: readonly RunEvent[],
): { markdown: string | null; draft: string | null } {
  const markdown = snapshot?.report?.markdown ?? null;
  const draft = markdown ? null : draftFromReview(events);
  return { markdown, draft };
}

export function draftFromReview(events: readonly RunEvent[]): string | null {
  const review = [...events].reverse().find((event) => event.type === "review.awaiting");
  const report = review?.payload.report;
  if (!report || typeof report !== "object") return null;
  const record = report as { title?: unknown; sections?: unknown };
  const lines = [`# ${typeof record.title === "string" && record.title ? record.title : "Draft"}`, ""];
  if (!Array.isArray(record.sections)) return null;
  for (const section of record.sections) {
    if (!section || typeof section !== "object") continue;
    const item = section as { heading?: unknown; body?: unknown; evidence_ids?: unknown };
    lines.push(`## ${typeof item.heading === "string" && item.heading ? item.heading : "Section"}`);
    lines.push(typeof item.body === "string" ? item.body : "");
    if (Array.isArray(item.evidence_ids) && item.evidence_ids.length > 0) {
      lines.push(item.evidence_ids.map((id) => String(id)).join(" "));
    }
    lines.push("");
  }
  const text = lines.join("\n").trim();
  return text || null;
}

export function channelLabel(connection: ConnectionState): string {
  if (connection === "live") return "connected";
  if (connection === "closed") return "closed";
  return "reconnecting";
}
