import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { getEvents, getReady, getRun, getUsage } from "../api/client";
import type { UsageFigures, UsageSnapshot } from "../api/types";
import { EMPTY_USAGE } from "../api/types";
import { useToken } from "../auth/token";
import { ErrorText, PageHeader, UsageFiguresList } from "../components/ui";
import { formatElapsed, formatUnknown, formatWhen } from "../domain/format";
import { sourcesSeenCount, statusLabel, usageFromEvents } from "../domain/runView";
import { runStore } from "../state/runStore";

/** Map /me/usage ledger fields into the shared metric list shape. */
export function usageFiguresFromSnapshot(data: UsageSnapshot): UsageFigures {
  return {
    llm_calls: data.llm_calls ?? null,
    prompt_tokens: data.prompt_tokens ?? null,
    completion_tokens: data.completion_tokens ?? null,
    total_tokens: data.total_tokens ?? null,
    search_calls: data.search_calls ?? null,
    estimated_cost_usd: data.estimated_cost_usd,
  };
}

function hasMeasuredUsage(usage: UsageFigures): boolean {
  return (
    usage.llm_calls != null ||
    usage.prompt_tokens != null ||
    usage.completion_tokens != null ||
    usage.total_tokens != null ||
    usage.search_calls != null
  );
}

function QuotaMeter({
  label,
  value,
  max,
  warn,
}: {
  label: string;
  value: number;
  max: number;
  warn?: boolean;
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className={`quota-meter${warn ? " quota-meter--warn" : ""}`}>
      <div className="quota-meter-top">
        <span>{label}</span>
        <strong>
          {value} / {max}
        </strong>
      </div>
      <div className="quota-meter-track" aria-hidden="true">
        <div className="quota-meter-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function UsagePage() {
  const { token } = useToken();
  const usage = useQuery({
    queryKey: ["usage"],
    enabled: Boolean(token),
    queryFn: () => getUsage(token as string),
  });
  const health = useQuery({ queryKey: ["health", "ready"], queryFn: getReady });
  const data = usage.data;
  const figures = data ? usageFiguresFromSnapshot(data) : EMPTY_USAGE;
  const capped = Boolean(
    data &&
      (data.global_active_runs >= data.global_max_active_runs ||
        data.global_daily_starts >= data.global_daily_cap),
  );
  const limitEntries = data ? Object.entries(data.limits) : [];

  return (
    <section className="stack usage-page">
      <PageHeader title="Your usage" lede="Runs and provider totals for this guest session only." />
      {usage.isPending ? <p role="status">Loading usage.</p> : null}
      <ErrorText error={usage.error} />
      {data ? (
        <>
          <p className="banner info">{data.note}</p>

          <div className="quota-grid">
            <div className={`quota-card${data.one_use_consumed ? " quota-card--spent" : ""}`}>
              <p className="meta">One-use allowance</p>
              <p className="quota-card-value">{data.one_use_consumed ? "0 left" : "1 left"}</p>
              <p className="meta">
                {data.one_use_consumed
                  ? data.one_use_refunded
                    ? "Consumed, then refunded earlier in this session."
                    : "This guest token already started its research run."
                  : "One research start remains for this guest token."}
              </p>
            </div>
            <QuotaMeter
              label="Active runs (global)"
              value={data.global_active_runs}
              max={data.global_max_active_runs}
              warn={data.global_active_runs >= data.global_max_active_runs}
            />
            <QuotaMeter
              label="Daily starts (global)"
              value={data.global_daily_starts}
              max={data.global_daily_cap}
              warn={data.global_daily_starts >= data.global_daily_cap}
            />
          </div>

          {capped ? (
            <p className="banner warning" role="status">
              Demo cap warning: {data.global_active_runs} of {data.global_max_active_runs} active
              runs, {data.global_daily_starts} of {data.global_daily_cap} daily starts.
            </p>
          ) : null}

          <section className="panel">
            <h2>Account usage</h2>
            <p className="meta">
              {hasMeasuredUsage(figures)
                ? "Summed from the usage ledger for finished runs owned by this guest."
                : "No measured provider usage yet. Totals appear after a run finishes and records ledger rows."}
            </p>
            <UsageFiguresList usage={figures} bare />
            <p className="meta">
              Estimated cost uses list-price token rates (Gemini Flash USD/1M) plus a search call
              rate — not an invoice. Unknown only when tokens and search calls were not measured.
            </p>
          </section>

          {limitEntries.length ? (
            <section className="panel">
              <h2>Session budgets</h2>
              <p className="meta">Server-enforced caps for each research run on this demo.</p>
              <dl className="metric-list">
                {limitEntries.map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replaceAll("_", " ")}</dt>
                    <dd>{formatUnknown(value)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}

          <section className="panel">
            <h2>Provider status</h2>
            <dl className="metric-list">
              <div>
                <dt>Service</dt>
                <dd>{health.data?.status ?? "unknown"}</dd>
              </div>
              <div>
                <dt>Database</dt>
                <dd>{health.data?.database ?? "unknown"}</dd>
              </div>
              <div>
                <dt>Router mode</dt>
                <dd>{health.data?.use_mock_provider ? "mock" : "live allowlist"}</dd>
              </div>
            </dl>
            <p className="meta">
              Ready means the API and database answered. This page does not measure provider uptime.
            </p>
          </section>

          <div className="table-wrap panel">
            <table>
              <caption className="meta">Runs for this guest</caption>
              <thead>
                <tr>
                  <th scope="col">Topic</th>
                  <th scope="col">Status</th>
                  <th scope="col">Started</th>
                  <th scope="col">Duration</th>
                  <th scope="col">Sources</th>
                  <th scope="col">Model calls</th>
                  <th scope="col">Stop reason</th>
                </tr>
              </thead>
              <tbody>
                {data.run_ids.length === 0 ? (
                  <tr>
                    <td colSpan={7}>No runs for this guest.</td>
                  </tr>
                ) : (
                  data.run_ids.map((runId) => <RunRow key={runId} runId={runId} />)
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}

function RunRow({ runId }: { runId: string }) {
  const { token } = useToken();
  const version = useSyncExternalStore(runStore.subscribe, runStore.getVersion, runStore.getVersion);
  void version;
  const run = useQuery({
    queryKey: ["run", runId],
    enabled: Boolean(token),
    queryFn: () => getRun(token as string, runId),
  });
  const events = useQuery({
    queryKey: ["events", runId, "seed"],
    enabled: Boolean(token),
    queryFn: () => getEvents(token as string, runId, 0),
  });

  const item = run.data;
  const entry = runStore.get(runId);
  const eventList = events.data?.events ?? entry?.events ?? [];
  const sources =
    events.data || entry?.snapshot
      ? sourcesSeenCount(eventList, entry?.snapshot?.sources.length)
      : null;
  // Ledger usage from the run row covers review_required runs, which have no usage.updated event yet.
  const rowUsage = entry?.snapshot?.usage ?? item?.usage ?? usageFromEvents(eventList);

  return (
    <tr>
      <td>
        <Link to={`/runs/${runId}`}>{item?.topic ?? "Loading…"}</Link>
      </td>
      <td>{item ? statusLabel(item.status) : "unknown"}</td>
      <td>{formatWhen(item?.created_at)}</td>
      <td>{item ? formatElapsed(item.started_at, item.finished_at) : "unknown"}</td>
      <td>{sources === null ? "unknown" : sources}</td>
      <td>{formatUnknown(rowUsage.llm_calls)}</td>
      <td>{item ? (item.stop_reason ?? "none recorded") : formatUnknown(null)}</td>
    </tr>
  );
}
