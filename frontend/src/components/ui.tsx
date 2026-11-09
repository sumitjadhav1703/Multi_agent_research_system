import { useState, type ReactNode } from "react";
import type { Banner, BannerTone } from "../domain/runView";
import { nextActionHint, statusLabel, type HintSurface } from "../domain/runView";
import { formatUnknown } from "../domain/format";
import type { ConnectionState, ResearchRun, UsageFigures } from "../api/types";
import { channelLabel } from "../domain/runView";

export function PageHeader({
  title,
  lede,
  actions,
}: {
  eyebrow?: string;
  title: string;
  lede?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {lede ? <p className="lede">{lede}</p> : null}
      </div>
      {actions ? <div className="header-actions">{actions}</div> : null}
    </header>
  );
}

/** Full-width banners for Ask / gate pages only. */
export function BannerList({ banners }: { banners: readonly Banner[] }) {
  if (banners.length === 0) return null;
  return (
    <div className="banner-stack" aria-live="polite">
      {banners.map((banner) => (
        <article key={banner.id} className={`banner ${banner.tone}`} role={banner.tone === "danger" ? "alert" : "status"}>
          <h2>{banner.title}</h2>
          <p>{banner.detail}</p>
        </article>
      ))}
    </div>
  );
}

const DISMISSED_NOTICES_KEY = "researchmind.dismissedNotices";

function readDismissedNotices(): Record<string, true> {
  try {
    const raw = sessionStorage.getItem(DISMISSED_NOTICES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    const out: Record<string, true> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (value === true) out[key] = true;
    }
    return out;
  } catch {
    return {};
  }
}

function writeDismissedNotices(map: Record<string, true>) {
  try {
    sessionStorage.setItem(DISMISSED_NOTICES_KEY, JSON.stringify(map));
  } catch {
    /* ignore quota / private mode */
  }
}

/**
 * Compact top-right notice cluster for run pages.
 * Dismissals persist for the browser tab session across Live / Report / Evidence.
 */
export function NoticeCluster({
  notices,
  stickyHint,
  scope = "run",
}: {
  notices: readonly Banner[];
  stickyHint?: string | null;
  /** Prefix so dismissals follow the run across pages. */
  scope?: string;
}) {
  const [dismissed, setDismissed] = useState(readDismissedNotices);
  const hintKey = `${scope}:hint`;
  const showHint = Boolean(stickyHint) && !dismissed[hintKey];
  const visible = notices.filter((notice) => !dismissed[`${scope}:${notice.id}`]);

  function dismiss(key: string) {
    setDismissed((prev) => {
      const next = { ...prev, [key]: true as const };
      writeDismissedNotices(next);
      return next;
    });
  }

  if (visible.length === 0 && !showHint) return null;

  return (
    <aside className="notice-cluster" aria-label="Run notices">
      {showHint && stickyHint ? (
        <div className="notice-chip notice-chip--hint" role="status">
          <span>{stickyHint}</span>
          <button
            type="button"
            className="notice-dismiss"
            aria-label="Dismiss status hint"
            onClick={() => dismiss(hintKey)}
          >
            ×
          </button>
        </div>
      ) : null}
      <div className="notice-stack" aria-live="polite">
        {visible.map((notice) => (
          <article
            key={notice.id}
            className={`notice-card tone-${notice.tone}`}
            role={notice.tone === "danger" ? "alert" : "status"}
          >
            <div className="notice-card-head">
              <h2>{notice.title}</h2>
              <button
                type="button"
                className="notice-dismiss"
                aria-label={`Dismiss ${notice.title}`}
                onClick={() => dismiss(`${scope}:${notice.id}`)}
              >
                ×
              </button>
            </div>
            <p>{notice.detail}</p>
          </article>
        ))}
      </div>
    </aside>
  );
}

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill tone-${toneFor(status)}`}>{statusLabel(status)}</span>;
}

function toneFor(status: string): BannerTone {
  if (status === "failed" || status === "expired" || status === "rejected") return "danger";
  if (status === "review_required" || status === "cancelled") return "warning";
  if (status === "completed") return "ok";
  return "info";
}

export function RunStatusBar({
  run,
  connection,
  hasAnswer = false,
  surface = "generic",
  compact = false,
}: {
  run: ResearchRun;
  connection: ConnectionState;
  hasAnswer?: boolean;
  surface?: HintSurface;
  /** When true, omit the next-action hint (shown in NoticeCluster instead). */
  compact?: boolean;
}) {
  const channel = channelLabel(connection);
  const hint = compact ? null : nextActionHint(run, hasAnswer, surface);
  return (
    <div className="status-bar">
      <StatusPill status={run.status} />
      <span>
        {connection === "live" ? `Live updates (${channel})` : `Saved on server (${channel})`}
        {hint ? ` · ${hint}` : ""}
      </span>
    </div>
  );
}

export function UsageFiguresList({
  usage,
  heading = "Usage",
  bare = false,
}: {
  usage: UsageFigures;
  heading?: string;
  /** Skip the outer panel when nested inside a CollapsiblePanel. */
  bare?: boolean;
}) {
  const rows: [string, number | string | null][] = [
    ["Model calls", usage.llm_calls],
    ["Prompt tokens", usage.prompt_tokens],
    ["Completion tokens", usage.completion_tokens],
    ["Total tokens", usage.total_tokens],
    ["Search calls", usage.search_calls],
    ["Estimated cost (USD)", usage.estimated_cost_usd],
  ];
  const body = (
    <dl className="metric-list">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{formatUnknown(value)}</dd>
        </div>
      ))}
    </dl>
  );
  if (bare) return body;
  return (
    <section className="panel">
      <h2>{heading}</h2>
      {body}
    </section>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "The request failed.";
  return (
    <p className="banner danger" role="alert">
      {message}
    </p>
  );
}
