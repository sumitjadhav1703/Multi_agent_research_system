import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { SectionHeading } from "../components/SectionMark";
import { ErrorText, NoticeCluster, PageHeader, RunStatusBar } from "../components/ui";
import { extractionLabel, formatWhen } from "../domain/format";
import { answerMarkdown, discoveredSources, nextActionHint, noticeBanners } from "../domain/runView";
import { useRunChannel } from "../hooks/useRunChannel";

export function EvidencePage() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  const { runQuery, events, snapshot, connection } = useRunChannel(runId);
  const sources = useMemo(() => snapshot?.sources ?? [], [snapshot]);
  const passages = useMemo(() => snapshot?.passages ?? [], [snapshot]);
  const claims = useMemo(() => snapshot?.claims ?? [], [snapshot]);
  const requestedPassage = params.get("passage");
  const requestedClaim = params.get("claim");
  const [domain, setDomain] = useState("all");
  const [method, setMethod] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [claimId, setClaimId] = useState<string | null>(requestedClaim);

  const domains = useMemo(() => [...new Set(sources.map((source) => source.domain).filter(Boolean))], [sources]);
  const methods = useMemo(
    () => [...new Set(sources.map((source) => source.extraction_method).filter(Boolean))],
    [sources],
  );
  const filtered = sources.filter((source) => {
    if (domain !== "all" && source.domain !== domain) return false;
    if (method !== "all" && source.extraction_method !== method) return false;
    return true;
  });
  const passageSource = passages.find((passage) => passage.evidence_id === requestedPassage)?.source_id;
  const activeSourceId = selectedId ?? passageSource ?? filtered[0]?.source_id ?? null;
  const active = sources.find((source) => source.source_id === activeSourceId) ?? null;
  const activeClaim = claims.find((claim) => claim.claim_id === (claimId ?? requestedClaim)) ?? null;
  const highlighted = new Set(activeClaim?.evidence_ids ?? (requestedPassage ? [requestedPassage] : []));
  const visiblePassages = passages.filter((passage) => passage.source_id === activeSourceId);
  const linkedClaims = claims.filter((claim) =>
    claim.evidence_ids.some((id) => visiblePassages.some((passage) => passage.evidence_id === id)),
  );

  const run = runQuery.data;
  if (runQuery.isPending) return <p role="status">Loading the saved run.</p>;
  if (runQuery.isError || !run) {
    const missing = runQuery.error instanceof ApiError && runQuery.error.status === 404;
    return <ErrorText error={missing ? new Error("This run is not available to this guest identity.") : runQuery.error} />;
  }

  const discovered = discoveredSources(events);
  const { markdown, draft } = answerMarkdown(snapshot, events);
  const answerBody = markdown ?? draft;
  const notices = noticeBanners({ run, events, snapshot, connection });
  const hint = nextActionHint(run, Boolean(answerBody), "evidence");

  return (
    <section className="stack">
      <div className="run-top">
        <PageHeader
          title={run.topic}
          lede="Pick a source → read the passage → see which claims it supports."
        />
        <NoticeCluster notices={notices} stickyHint={hint} />
      </div>
      <RunStatusBar
        run={run}
        connection={connection}
        hasAnswer={Boolean(answerBody)}
        surface="evidence"
        compact
      />
      <p className="evidence-lede">
        Evidence explains what the answer is allowed to claim. Titles first; technical IDs stay in the meta line.
      </p>
      {sources.length === 0 ? (
        <section className="panel">
          <SectionHeading kind="sources">Sources</SectionHeading>
          <p>No stored sources for this run yet.</p>
          {discovered.length === 0 ? null : (
            <ul className="feed">
              {discovered.map((source) => (
                <li key={source.sourceId}>
                  {source.sourceId} · {extractionLabel(source.extractionMethod)} · progress event, not a stored passage
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : (
        <div className="evidence-grid">
          <section className="panel">
            <SectionHeading kind="sources">Sources</SectionHeading>
            <div className="evidence-filters">
              <label className="field">
                <span>Domain</span>
                <select value={domain} onChange={(event) => setDomain(event.target.value)}>
                  <option value="all">All domains</option>
                  {domains.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Extraction</span>
                <select value={method} onChange={(event) => setMethod(event.target.value)}>
                  <option value="all">All methods</option>
                  {methods.map((item) => (
                    <option key={item} value={item}>
                      {extractionLabel(item)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="source-list">
              {filtered.map((source) => (
                <button
                  key={source.source_id}
                  type="button"
                  className="source-pill"
                  aria-pressed={source.source_id === activeSourceId}
                  onClick={() => setSelectedId(source.source_id)}
                >
                  <span className="source-pill-title">
                    {source.title || source.domain || "Untitled source"}
                  </span>
                  <span className="meta source-pill-meta">
                    {source.domain}
                    <span aria-hidden="true"> · </span>
                    {source.source_id}
                  </span>
                </button>
              ))}
            </div>
          </section>

          <section className="panel evidence-reader">
            <h2>{active?.title || active?.domain || "Passage reader"}</h2>
            {active ? (
              <>
                <p className="meta">
                  {extractionLabel(active.extraction_method)} · Retrieved {formatWhen(active.retrieved_at)} ·
                  Publication date unknown
                </p>
                <p className="meta">{active.source_id}</p>
                <p>{active.excerpt || "No excerpt stored."}</p>
              </>
            ) : (
              <p>Select a source on the left.</p>
            )}
            {visiblePassages.map((passage) => (
              <article
                key={passage.evidence_id}
                id={passage.evidence_id}
                className={highlighted.has(passage.evidence_id) ? "passage highlight" : "passage"}
              >
                <h3>Stored passage</h3>
                <p className="meta">{passage.evidence_id}</p>
                <p>{passage.quote}</p>
              </article>
            ))}
            {active && visiblePassages.length === 0 ? <p>No passage is stored for this source.</p> : null}
          </section>

          <section className="panel">
            <SectionHeading kind="critics">Claims</SectionHeading>
            {claims.length === 0 ? (
              <p>No claim ledger for this run. The answer may still exist without per-claim rows.</p>
            ) : (
              <div className="claim-list">
                {(linkedClaims.length > 0 ? linkedClaims : claims).map((claim) => (
                  <button
                    key={claim.claim_id}
                    type="button"
                    className="secondary"
                    aria-pressed={claim.claim_id === (claimId ?? requestedClaim)}
                    onClick={() => {
                      setClaimId(claim.claim_id);
                      const passage = passages.find((item) => claim.evidence_ids.includes(item.evidence_id));
                      if (passage) setSelectedId(passage.source_id);
                    }}
                  >
                    <strong>{claim.text}</strong>
                    <span className="meta">
                      {" "}
                      {claim.status} · {claim.claim_id}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {activeClaim ? (
              <p style={{ marginTop: "0.75rem" }}>{activeClaim.verification_reason ?? "No verification note stored."}</p>
            ) : null}
          </section>
        </div>
      )}
    </section>
  );
}
