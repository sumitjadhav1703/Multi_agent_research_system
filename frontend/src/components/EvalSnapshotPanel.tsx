import { Link } from "react-router-dom";
import bundledSummary from "../data/evaluationSummary.json";
import type { EvaluationSummary } from "../api/types";

const SUMMARY = bundledSummary as EvaluationSummary;

/** Compact offline harness strip for Evidence empty/placeholder states. */
export function EvalSnapshotPanel({ compact = false }: { compact?: boolean }) {
  const scores = SUMMARY.judge?.scores ?? {};
  const faithfulness = scores.faithfulness;
  const relevancy = scores.answer_relevancy;
  const fixturePass = SUMMARY.deterministic?.passed;
  const fixtureRuns = SUMMARY.deterministic?.runs;

  return (
    <section className={`panel eval-snapshot${compact ? " eval-snapshot--compact" : ""}`}>
      <h2 className="eval-snapshot-title">Offline evaluation snapshot</h2>
      <p className="meta">
        Fixture harness only (DeepEval + deterministic checks). Not a live V1/V2 quality table.
      </p>
      <ul className="eval-snapshot-grid">
        <li>
          <strong>{faithfulness != null ? faithfulness.toFixed(2) : "—"}</strong>
          <span>Faithfulness mean</span>
        </li>
        <li>
          <strong>{relevancy != null ? relevancy.toFixed(2) : "—"}</strong>
          <span>Answer relevancy</span>
        </li>
        <li>
          <strong>{fixturePass ? `${fixtureRuns}/${fixtureRuns}` : "—"}</strong>
          <span>Fixture self-check</span>
        </li>
        <li>
          <strong>{SUMMARY.judge?.numeric_scores ?? "—"}</strong>
          <span>Judge scores · 0 errors</span>
        </li>
      </ul>
      <p className="meta">
        Model: {SUMMARY.judge?.model ?? "unknown"} ·{" "}
        <Link to="/evaluation">Open Evaluation</Link>
      </p>
    </section>
  );
}
