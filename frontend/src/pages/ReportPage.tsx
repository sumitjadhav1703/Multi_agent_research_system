import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { CollapsiblePanel } from "../components/CollapsiblePanel";
import { ExpandableMarkdown } from "../components/ExpandableMarkdown";
import { ReviewForm } from "../components/ReviewForm";
import { SectionHeading } from "../components/SectionMark";
import { ErrorText, NoticeCluster, PageHeader, RunStatusBar, UsageFiguresList } from "../components/ui";
import { formatElapsed } from "../domain/format";
import { answerMarkdown, nextActionHint, noticeBanners, revisionsUsed, usageFromEvents } from "../domain/runView";
import { useFirstVisitExpand } from "../hooks/useFirstVisitExpand";
import { useRunChannelContext } from "../hooks/runChannelContext";

export function ReportPage() {
  const { runId = "" } = useParams();
  const expandSecondary = useFirstVisitExpand(`report:${runId || "none"}`);
  const { runQuery, events, snapshot, connection } = useRunChannelContext();
  const run = runQuery.data;
  const citationIds = useMemo(
    () => [
      ...(snapshot?.passages.map((passage) => passage.evidence_id) ?? []),
      ...(snapshot?.claims.map((claim) => claim.claim_id) ?? []),
      ...(snapshot?.sources.map((source) => source.source_id) ?? []),
    ],
    [snapshot],
  );
  const allowedUrls = useMemo(
    () => snapshot?.sources.flatMap((source) => [source.url, source.canonical_url]) ?? [],
    [snapshot],
  );

  if (runQuery.isPending) return <p role="status">Loading the saved run.</p>;
  if (runQuery.isError || !run) {
    const missing = runQuery.error instanceof ApiError && runQuery.error.status === 404;
    return <ErrorText error={missing ? new Error("This run is not available to this guest identity.") : runQuery.error} />;
  }

  const { markdown, draft } = answerMarkdown(snapshot, events);
  const answerBody = markdown ?? draft;
  const usage = snapshot?.usage ?? usageFromEvents(events);
  const conflicts = snapshot?.claims.filter((claim) => claim.status === "contradictory") ?? [];
  const gaps = snapshot?.claims.filter((claim) => claim.status === "insufficient") ?? [];
  const notices = noticeBanners({ run, events, snapshot, connection });
  const hint = nextActionHint(run, Boolean(answerBody), "report");

  return (
    <section className="stack report-doc">
      <div className="run-top">
        <div className="run-top-main">
          <PageHeader
            title={run.topic}
            lede={snapshot?.wording ?? "Evidence assessed against stored passages. This is not an absolute fact-check."}
            actions={
              answerBody ? (
                <div className="button-row no-print">
                  <button type="button" onClick={() => downloadMarkdown(run.run_id, answerBody)}>
                    Export Markdown
                  </button>
                  <button type="button" className="secondary" onClick={() => window.print()}>
                    Print / save as PDF
                  </button>
                </div>
              ) : null
            }
          />
          <div className="no-print">
            <RunStatusBar
              run={run}
              connection={connection}
              hasAnswer={Boolean(answerBody)}
              surface="report"
              compact
            />
            <p className="meta">
              Duration {formatElapsed(run.started_at, run.finished_at)} · Sources{" "}
              {snapshot ? snapshot.sources.length : "unknown"} · Evaluation not measured for this run
            </p>
          </div>
        </div>
        <div className="no-print">
          <NoticeCluster notices={notices} stickyHint={hint} scope={run.run_id} />
        </div>
      </div>
      {run.status === "review_required" ? (
        <div className="no-print">
          <ReviewForm runId={run.run_id} canRevise={revisionsUsed(events) === 0} />
        </div>
      ) : null}

      <article className="answer-panel" aria-labelledby="report-answer-heading">
        <SectionHeading kind="answer">Answer</SectionHeading>
        <h3 id="report-answer-heading" className="visually-hidden">
          Full research answer
        </h3>
        {markdown ? (
          <ExpandableMarkdown
            markdown={markdown}
            citationIds={citationIds}
            allowedUrls={allowedUrls}
            runId={run.run_id}
            lines={5}
          />
        ) : null}
        {!markdown && draft ? (
          <>
            <p className="banner warning">
              Truncated excerpt from the review event. The full stored report has not arrived.
            </p>
            <ExpandableMarkdown
              markdown={draft}
              citationIds={citationIds}
              allowedUrls={allowedUrls}
              runId={run.run_id}
              lines={10}
            />
          </>
        ) : null}
        {!markdown && !draft ? (
          <p className="answer-empty">
            No persisted report is available yet. If the run finished without a write-up, check Critics and{" "}
            <Link to={`/runs/${run.run_id}/evidence`}>Evidence</Link>.
          </p>
        ) : null}
      </article>

      <CollapsiblePanel
        title="Critics"
        defaultOpen={expandSecondary}
        count={conflicts.length + gaps.length || null}
        className="no-print"
      >
        {conflicts.length === 0 && gaps.length === 0 ? (
          <p>No claim-level conflicts or insufficient gaps are stored for this run.</p>
        ) : null}
        {conflicts.map((claim) => (
          <p key={claim.claim_id}>
            <strong>Conflict</strong> <span className="meta">{claim.claim_id}</span> — {claim.text}
          </p>
        ))}
        {gaps.map((claim) => (
          <p key={claim.claim_id}>
            <strong>Insufficient</strong> <span className="meta">{claim.claim_id}</span> — {claim.text}
            {claim.verification_reason ? ` (${claim.verification_reason})` : ""}
          </p>
        ))}
      </CollapsiblePanel>

      <CollapsiblePanel
        title="Sources"
        defaultOpen={expandSecondary}
        count={snapshot?.sources.length ?? null}
        className="no-print"
      >
        {snapshot?.sources.length ? (
          <ul className="feed">
            {snapshot.sources.map((source) => (
              <li key={source.source_id}>
                <strong>{source.title || source.source_id}</strong>
                <div className="meta">{source.domain}</div>
                <div className="meta">Publication date: unknown</div>
              </li>
            ))}
          </ul>
        ) : (
          <p>No citation sources are stored yet.</p>
        )}
        <div className="button-row" style={{ marginTop: "0.75rem" }}>
          <Link className="button secondary" to={`/runs/${run.run_id}/evidence`}>
            Open evidence explorer
          </Link>
        </div>
      </CollapsiblePanel>

      <CollapsiblePanel
        title="Run usage"
        defaultOpen={expandSecondary}
        className="report-secondary no-print"
      >
        <UsageFiguresList usage={usage} bare />
      </CollapsiblePanel>
    </section>
  );
}

/** Download report text as .md (document body only, not a page screenshot). */
export function downloadMarkdown(runId: string, markdown: string) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `researchmind-${runId}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
