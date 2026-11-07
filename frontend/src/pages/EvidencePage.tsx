import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { BannerList, ErrorText, PageHeader, RunStatusBar } from "../components/ui";
import { extractionLabel, formatWhen } from "../domain/format";
import { discoveredSources, runBanners } from "../domain/runView";
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

  return (
    <section className="stack">
      <PageHeader
        eyebrow="Evidence explorer"
        title={run.topic}
        lede="Passages and claims come from the saved snapshot. Publication dates are not stored."
      />
      <RunStatusBar run={run} connection={connection} />
      <BannerList banners={runBanners({ run, events, snapshot, connection })} />
      {sources.length === 0 ? (
        <section className="panel">
          <h2>No stored sources</h2>
          {discovered.length === 0 ? <p>Evidence has not been stored for this run yet.</p> : null}
          <ul className="feed">
            {discovered.map((source) => (
              <li key={source.sourceId}>
                {source.sourceId} · {extractionLabel(source.extractionMethod)} · progress event, not a stored passage
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <div className="evidence-grid">
          <section className="panel">
            <h2>Sources</h2>
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
            <div className="source-list">
              {filtered.map((source) => (
                <button
                  key={source.source_id}
                  type="button"
                  aria-pressed={source.source_id === activeSourceId}
                  onClick={() => setSelectedId(source.source_id)}
                >
                  {source.title || source.source_id}
                  <span className="meta"> {source.domain}</span>
                </button>
              ))}
            </div>
          </section>
          <section className="panel">
            <h2>{active?.title || "Passage"}</h2>
            {active ? (
              <>
                <p className="meta">{extractionLabel(active.extraction_method)}</p>
                <p className="meta">Retrieved: {formatWhen(active.retrieved_at)}</p>
                <p className="meta">Publication date: unknown</p>
                <p>{active.excerpt || "No excerpt stored."}</p>
              </>
            ) : (
              <p>Select a source.</p>
            )}
            {visiblePassages.map((passage) => (
              <article
                key={passage.evidence_id}
                id={passage.evidence_id}
                className={highlighted.has(passage.evidence_id) ? "passage highlight" : "passage"}
              >
                <h3>{passage.evidence_id}</h3>
                <p>{passage.quote}</p>
              </article>
            ))}
            {active && visiblePassages.length === 0 ? <p>No passage is stored for this source.</p> : null}
          </section>
          <section className="panel">
            <h2>Claims</h2>
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
                <strong>{claim.claim_id}</strong> · {claim.status}
                <span className="meta"> {claim.text}</span>
              </button>
            ))}
            {claims.length === 0 ? <p>No claims are stored yet.</p> : null}
            {activeClaim ? <p>{activeClaim.verification_reason ?? "No verification note stored."}</p> : null}
          </section>
        </div>
      )}
    </section>
  );
}
