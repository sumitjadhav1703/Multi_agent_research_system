import { Link, useLocation, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { EMPTY_USAGE } from "../api/types";
import { CollapsiblePanel } from "../components/CollapsiblePanel";
import { ExpandableMarkdown } from "../components/ExpandableMarkdown";
import { CancelRun } from "../components/ReviewForm";
import { SectionHeading } from "../components/SectionMark";
import { StageMark, stageMarkKind } from "../components/StageMark";
import { ErrorText, NoticeCluster, PageHeader, RunStatusBar, UsageFiguresList } from "../components/ui";
import { formatElapsed, formatWhen, extractionLabel } from "../domain/format";
import {
  ACTIVE_STATUSES,
  answerMarkdown,
  discoveredSources,
  nextActionHint,
  noticeBanners,
  stageStates,
  summarizeEvent,
  usageFromEvents,
  workerCards,
} from "../domain/runView";
import { useFirstVisitExpand } from "../hooks/useFirstVisitExpand";
import { useRunChannel } from "../hooks/useRunChannel";

export function LiveRunPage() {
  const { runId = "" } = useParams();
  const location = useLocation();
  const reused = Boolean((location.state as { reused?: boolean } | null)?.reused);
  const expandSecondary = useFirstVisitExpand(`live:${runId || "none"}`);
  const { runQuery, events, snapshot, connection } = useRunChannel(runId);
  const run = runQuery.data;

  if (runQuery.isPending) return <p role="status">Loading the saved run.</p>;
  if (runQuery.isError || !run) {
    const missing = runQuery.error instanceof ApiError && runQuery.error.status === 404;
    return <ErrorText error={missing ? new Error("This run is not available to this guest identity.") : runQuery.error} />;
  }

  const notices = noticeBanners({ run, events, snapshot, connection });
  const stages = stageStates(events, run.status);
  const workers = workerCards(events);
  const sources = snapshot?.sources ?? [];
  const discovered = discoveredSources(events);
  const usage = snapshot?.usage ?? usageFromEvents(events) ?? EMPTY_USAGE;
  const { markdown, draft } = answerMarkdown(snapshot, events);
  const answerBody = markdown ?? draft;
  const hint = nextActionHint(run, Boolean(answerBody), "live");
  const citationIds = [
    ...(snapshot?.passages.map((passage) => passage.evidence_id) ?? []),
    ...(snapshot?.claims.map((claim) => claim.claim_id) ?? []),
    ...(snapshot?.sources.map((source) => source.source_id) ?? []),
  ];
  const allowedUrls = [
    ...(snapshot?.sources.flatMap((source) => [source.url, source.canonical_url]) ?? []),
  ];
  const doneCount = stages.filter((stage) => stage.state === "done").length;
  const sourceCount = sources.length || discovered.length;

  return (
    <section className="stack">
      <div className="run-top">
        <div className="run-top-main">
          <PageHeader
            title={run.topic}
            lede="Follow the process rail, then read the answer when it lands."
            actions={
              <div className="button-row">
                <Link className="button" to={`/runs/${run.run_id}/report`}>
                  Open report
                </Link>
                <Link className="button secondary" to={`/runs/${run.run_id}/evidence`}>
                  Evidence
                </Link>
              </div>
            }
          />
          {reused ? <p className="banner info">Reopened your existing run.</p> : null}
          <RunStatusBar run={run} connection={connection} hasAnswer={Boolean(answerBody)} surface="live" compact />
        </div>
        <NoticeCluster notices={notices} stickyHint={hint} scope={run.run_id} />
      </div>

      <div className="process-shell">
        <div className="process-shell-head">
          <SectionHeading kind="flow">Process</SectionHeading>
          <p className="meta process-progress">
            {doneCount} of {stages.length} stages
          </p>
        </div>
        <ol className="process-rail" aria-label="Research stages">
          {stages.map((stage, index) => (
            <li
              key={stage.id}
              className={`${stage.state} stage-${stage.id}`}
              aria-current={stage.state === "active" ? "step" : undefined}
            >
              {index > 0 ? <span className="step-connector" aria-hidden="true" /> : null}
              <span className="step-index" aria-hidden="true">
                {index + 1}
              </span>
              <span className="step-icon" aria-hidden="true">
                <StageMark kind={stageMarkKind(stage.id)} />
              </span>
              <span className="step-label">{stage.label}</span>
              <span className="step-blurb">{stage.blurb}</span>
              <span className="step-state">
                <span className="visually-hidden">Status: </span>
                {stage.state}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <div className="live-cockpit">
        <article className="answer-panel" aria-labelledby="live-answer-heading">
          <SectionHeading kind="answer">Answer</SectionHeading>
          <h3 id="live-answer-heading" className="visually-hidden">
            Research answer
          </h3>
          {answerBody ? (
            <>
              {draft && !markdown ? (
                <p className="banner warning">Draft excerpt from review. Full stored report may still be arriving.</p>
              ) : null}
              <ExpandableMarkdown
                markdown={answerBody}
                citationIds={citationIds}
                allowedUrls={allowedUrls}
                runId={run.run_id}
                lines={7}
              />
              <div className="button-row" style={{ marginTop: "0.85rem" }}>
                <Link className="button" to={`/runs/${run.run_id}/report`}>
                  Open full report
                </Link>
              </div>
            </>
          ) : (
            <p className="answer-empty">
              {ACTIVE_STATUSES.has(run.status)
                ? "No stored answer yet. The write-up appears here when the report stage finishes."
                : "No stored answer for this run. Check Critics and Evidence for what was assessed."}
            </p>
          )}
        </article>

        <aside className="live-drawers">
          <CollapsiblePanel title="Usage" defaultOpen={expandSecondary}>
            <UsageFiguresList usage={usage} bare />
          </CollapsiblePanel>

          <CollapsiblePanel title="Sources" defaultOpen={expandSecondary} count={sourceCount || null}>
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
          </CollapsiblePanel>

          <CollapsiblePanel title="Activity" defaultOpen={expandSecondary} count={events.length || null}>
            <p className="meta">
              Elapsed {formatElapsed(run.started_at, run.finished_at)} · Attempts {run.attempts} ·{" "}
              {run.stop_reason ?? "no stop reason"}
            </p>
            {events.length === 0 ? <p>No events saved yet.</p> : null}
            <ul className="feed activity-feed" aria-live="polite">
              {events.slice(-80).map((event) => (
                <li key={event.sequence_id}>
                  <time dateTime={event.created_at}>{formatWhen(event.created_at)}</time>{" "}
                  <strong>{event.type}</strong>
                  <div>{summarizeEvent(event)}</div>
                </li>
              ))}
            </ul>
          </CollapsiblePanel>

          <CollapsiblePanel title="Workers" defaultOpen={expandSecondary} count={workers.length || null}>
            {workers.length === 0 ? (
              <p>No worker events yet. Provider name is unknown until an event includes one.</p>
            ) : null}
            <ul className="worker-rows">
              {workers.map((worker) => (
                <li key={worker.subquestionId}>
                  <strong>{worker.subquestionId}</strong>
                  <span className="meta">{worker.state}</span>
                  <span className="meta">
                    Provider {worker.provider} · Sources{" "}
                    {worker.sources === null ? "unknown" : worker.sources}
                    {worker.error ? ` · ${worker.error}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </CollapsiblePanel>
        </aside>
      </div>

      {ACTIVE_STATUSES.has(run.status) ? <CancelRun runId={run.run_id} /> : null}
    </section>
  );
}
