import type { ReactNode } from "react";
import type { Banner, BannerTone } from "../domain/runView";
import { statusLabel } from "../domain/runView";
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

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill tone-${toneFor(status)}`}>{statusLabel(status)}</span>;
}

function toneFor(status: string): BannerTone {
  if (status === "failed" || status === "expired") return "danger";
  if (status === "review_required" || status === "cancelled") return "warning";
  if (status === "completed") return "ok";
  return "info";
}

export function RunStatusBar({ run, connection }: { run: ResearchRun; connection: ConnectionState }) {
  const channel = channelLabel(connection);
  return (
    <p className="status-bar">
      <StatusPill status={run.status} />
      <span>
        Saved status: {statusLabel(run.status)}. Progress channel: {channel}.
        {connection === "live" ? "" : " The status is the saved run from the server."}
      </span>
    </p>
  );
}

export function UsageFiguresList({ usage, heading = "Usage" }: { usage: UsageFigures; heading?: string }) {
  const rows: [string, number | string | null][] = [
    ["Model calls", usage.llm_calls],
    ["Prompt tokens", usage.prompt_tokens],
    ["Completion tokens", usage.completion_tokens],
    ["Total tokens", usage.total_tokens],
    ["Search calls", usage.search_calls],
    ["Estimated cost (USD)", usage.estimated_cost_usd],
  ];
  return (
    <section className="panel">
      <h2>{heading}</h2>
      <dl className="metric-list">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{formatUnknown(value)}</dd>
          </div>
        ))}
      </dl>
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
