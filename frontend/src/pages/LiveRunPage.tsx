import { Link, useLocation, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { EMPTY_USAGE } from "../api/types";
import { CancelRun } from "../components/ReviewForm";
import { BannerList, ErrorText, PageHeader, RunStatusBar, UsageFiguresList } from "../components/ui";
import { formatElapsed, formatWhen, extractionLabel } from "../domain/format";
import {
  ACTIVE_STATUSES,
  discoveredSources,
  runBanners,
  stageStates,
  summarizeEvent,
  usageFromEvents,
  workerCards,
} from "../domain/runView";
import { useRunChannel } from "../hooks/useRunChannel";

export function LiveRunPage() {
  const { runId = "" } = useParams();
  const location = useLocation();
  const reused = Boolean((location.state as { reused?: boolean } | null)?.reused);
  const { runQuery, events, snapshot, connection } = useRunChannel(runId);
  const run = runQuery.data;

  if (runQuery.isPending) return <p role="status">Loading the saved run.</p>;
  if (runQuery.isError || !run) {
    const missing = runQuery.error instanceof ApiError && runQuery.error.status === 404;
    return <ErrorText error={missing ? new Error("This run is not available to this guest identity.") : runQuery.error} />;
  }

  const banners = runBanners({ run, events, snapshot, connection });
  const stages = stageStates(events, run.status);
  const workers = workerCards(events);
  const sources = snapshot?.sources ?? [];
  const discovered = discoveredSources(events);
  const usage = snapshot?.usage ?? usageFromEvents(events) ?? EMPTY_USAGE;

  return (
    <section className="stack">
      <PageHeader
        title={run.topic}
        lede="Live progress from the saved run log."
        actions={
          <div className="button-row">
            <Link className="button secondary" to={`/runs/${run.run_id}/report`}>
              Report
            </Link>
            <Link className="button secondary" to={`/runs/${run.run_id}/evidence`}>
              Evidence
            </Link>
          </div>
        }
      />
      {reused ? <p className="banner info">Reopened your existing run.</p> : null}
      <RunStatusBar run={run} connection={connection} />
      <BannerList banners={banners} />
      <dl className="metric-list">
        <div>
          <dt>Elapsed</dt>
          <dd>{formatElapsed(run.started_at, run.finished_at)}</dd>
        </div>
        <div>
          <dt>Attempts</dt>
          <dd>{run.attempts}</dd>
        </div>
        <div>
          <dt>Stop reason</dt>
          <dd>{run.stop_reason ?? "none recorded"}</dd>
        </div>
        <div>
          <dt>Approval</dt>
          <dd>{run.approval_status ?? "unknown"}</dd>
        </div>
      </dl>
      <ol className="timeline" aria-label="Research stages">
        {stages.map((stage) => (
          <li key={stage.id} className={stage.state}>
            <strong>{stage.label}</strong>
            <span>{stage.state}</span>
          </li>
        ))}
      </ol>
      <div className="split">
        <section className="panel">
          <h2>Activity</h2>
          {events.length === 0 ? <p>No events saved yet.</p> : null}
          <ul className="feed" aria-live="polite">
            {events.slice(-80).map((event) => (
              <li key={event.sequence_id}>
                <time dateTime={event.created_at}>{formatWhen(event.created_at)}</time>{" "}
                <strong>{event.type}</strong>
                <div>{summarizeEvent(event)}</div>
              </li>
            ))}
          </ul>
        </section>
        <div className="stack">
          <UsageFiguresList usage={usage} />
          <section className="panel">
            <h2>Sources</h2>
            {sources.length === 0 && discovered.length === 0 ? <p>No sources saved yet.</p> : null}
            <ul className="feed">
              {sources.map((source) => (
                <li key={source.source_id}>
                  <strong>{source.title || source.domain || source.source_id}</strong>
                  <div className="meta">{extractionLabel(source.extraction_method)}</div>
                </li>
              ))}
              {sources.length === 0
                ? discovered.map((source) => (
                    <li key={source.sourceId}>
                      <strong>{source.sourceId}</strong>
                      <div className="meta">{extractionLabel(source.extractionMethod)} · from the event log</div>
                    </li>
                  ))
                : null}
            </ul>
          </section>
        </div>
      </div>
      <section className="panel">
        <h2>Workers</h2>
        {workers.length === 0 ? <p>No worker events yet. Provider name is unknown until an event includes one.</p> : null}
        <div className="timeline">
          {workers.map((worker) => (
            <article key={worker.subquestionId} className="card">
              <h3>{worker.subquestionId}</h3>
              <p>State: {worker.state}</p>
              <p>Provider: {worker.provider}</p>
              <p>Sources: {worker.sources === null ? "unknown" : worker.sources}</p>
              {worker.error ? <p>{worker.error}</p> : null}
            </article>
          ))}
        </div>
      </section>
      {ACTIVE_STATUSES.has(run.status) ? <CancelRun runId={run.run_id} /> : null}
    </section>
  );
}
