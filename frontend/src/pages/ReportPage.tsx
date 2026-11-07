import { useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { MarkdownView } from "../components/MarkdownView";
import { ReviewForm } from "../components/ReviewForm";
import { BannerList, ErrorText, PageHeader, RunStatusBar, UsageFiguresList } from "../components/ui";
import { formatElapsed } from "../domain/format";
import { draftFromReview, runBanners, usageFromEvents } from "../domain/runView";
import { useRunChannel } from "../hooks/useRunChannel";
import { EMPTY_USAGE } from "../api/types";

export function ReportPage() {
  const { runId = "" } = useParams();
  const { runQuery, events, snapshot, connection } = useRunChannel(runId);
  const run = runQuery.data;

  if (runQuery.isPending) return <p role="status">Loading the saved run.</p>;
  if (runQuery.isError || !run) {
    const missing = runQuery.error instanceof ApiError && runQuery.error.status === 404;
    return <ErrorText error={missing ? new Error("This run is not available to this guest identity.") : runQuery.error} />;
  }

  const markdown = snapshot?.report?.markdown ?? null;
  const draft = markdown ? null : draftFromReview(events);
  const citationIds = [
    ...(snapshot?.passages.map((passage) => passage.evidence_id) ?? []),
    ...(snapshot?.claims.map((claim) => claim.claim_id) ?? []),
    ...(snapshot?.sources.map((source) => source.source_id) ?? []),
  ];
  const allowedUrls = [
    ...(snapshot?.sources.flatMap((source) => [source.url, source.canonical_url]) ?? []),
  ];
  const usage = snapshot?.usage ?? usageFromEvents(events);
  const conflicts = snapshot?.claims.filter((claim) => claim.status === "contradictory") ?? [];
  const gaps = snapshot?.claims.filter((claim) => claim.status === "insufficient") ?? [];

  return (
    <section className="stack">
      <PageHeader
        title={run.topic}
        lede={snapshot?.wording ?? "Evidence assessed against stored passages. This is not an absolute fact-check."}
        actions={
          markdown ? (
            <div className="button-row no-print">
              <button type="button" onClick={() => downloadMarkdown(run.run_id, markdown)}>
                Export Markdown
              </button>
              <button type="button" className="secondary" onClick={() => window.print()}>
                Print / save as PDF
              </button>
            </div>
          ) : null
        }
      />
      <RunStatusBar run={run} connection={connection} />
      <BannerList banners={runBanners({ run, events, snapshot, connection })} />
      <dl className="metric-list">
        <div>
          <dt>Duration</dt>
          <dd>{formatElapsed(run.started_at, run.finished_at)}</dd>
        </div>
        <div>
          <dt>Sources</dt>
          <dd>{snapshot ? snapshot.sources.length : "unknown"}</dd>
        </div>
        <div>
          <dt>Model calls</dt>
          <dd>{usage.llm_calls === null ? "unknown" : usage.llm_calls}</dd>
        </div>
        <div>
          <dt>Evaluation</dt>
          <dd>not measured</dd>
        </div>
      </dl>
      {run.status === "review_required" ? <ReviewForm runId={run.run_id} /> : null}
      <div className="split">
        <article className="panel">
          {markdown ? (
            <MarkdownView markdown={markdown} citationIds={citationIds} allowedUrls={allowedUrls} runId={run.run_id} />
          ) : null}
          {!markdown && draft ? (
            <>
              <p className="banner warning">Truncated excerpt from the review event. The full stored report has not arrived.</p>
              <MarkdownView markdown={draft} citationIds={citationIds} allowedUrls={allowedUrls} runId={run.run_id} />
            </>
          ) : null}
          {!markdown && !draft ? <p>No persisted report is available yet.</p> : null}
        </article>
        <aside className="stack">
          <UsageFiguresList usage={usage ?? EMPTY_USAGE} heading="Run usage" />
          <section className="panel">
            <h2>Limitations</h2>
            {conflicts.length === 0 && gaps.length === 0 ? <p>No claim-level conflicts or gaps are stored yet.</p> : null}
            {conflicts.map((claim) => (
              <p key={claim.claim_id}>
                Conflict {claim.claim_id}: {claim.text}
              </p>
            ))}
            {gaps.map((claim) => (
              <p key={claim.claim_id}>
                Insufficient {claim.claim_id}: {claim.text}
              </p>
            ))}
          </section>
          <section className="panel">
            <h2>Citations</h2>
            {snapshot?.sources.length ? (
              <ul className="feed">
                {snapshot.sources.map((source) => (
                  <li key={source.source_id}>
                    <strong>{source.title || source.source_id}</strong>
                    <div className="meta">Publication date: unknown</div>
                    <div className="meta">{source.domain}</div>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No citation sources are stored yet.</p>
            )}
          </section>
        </aside>
      </div>
    </section>
  );
}

function downloadMarkdown(runId: string, markdown: string) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `researchmind-${runId}.md`;
  link.click();
  URL.revokeObjectURL(url);
}
