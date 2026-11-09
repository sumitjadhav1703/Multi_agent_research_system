import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getEvaluationSummary } from "../api/client";
import type { EvaluationSummary } from "../api/types";
import { useToken } from "../auth/token";
import bundledSummary from "../data/evaluationSummary.json";
import { PageHeader } from "../components/ui";

const FALLBACK = bundledSummary as EvaluationSummary;

function metricRows(summary: EvaluationSummary): { metric: string; result: string }[] {
  const judgeMetrics = summary.judge?.metrics ?? [];
  const rows = judgeMetrics.map((row) => ({
    metric: row.name.replaceAll("_", " "),
    result: row.result,
  }));
  rows.push({
    metric: "Citation / fixture self-check",
    result: summary.deterministic?.passed
      ? `${summary.deterministic.runs}/${summary.deterministic.runs} matched expectations`
      : summary.deterministic
        ? `${summary.deterministic.fixture_mismatches} mismatch(es)`
        : "not measured",
  });
  rows.push({
    metric: "Invalid citations (fixture pack)",
    result: summary.citation_checks?.fixture_self_check_passed
      ? "expected failure codes matched"
      : "not measured",
  });
  if (rows.length === 0) {
    return [{ metric: "scores", result: "not measured" }];
  }
  return rows;
}

function metadataRows(summary: EvaluationSummary): [string, string][] {
  return [
    ["Dataset version", summary.dataset ?? "unknown"],
    ["Cases", String(summary.dataset_cases ?? "unknown")],
    ["Evaluator model", summary.judge?.model ?? "unknown"],
    ["DeepEval version", summary.judge?.deepeval_version ?? "unknown"],
    ["Run date", summary.run_date ?? "unknown"],
    [
      "LLM judge measured",
      summary.judge?.measured ? "yes" : "no (null scores are not zeros)",
    ],
    [
      "Deterministic fixtures",
      summary.deterministic
        ? `${summary.deterministic.runs} runs, mismatches=${summary.deterministic.fixture_mismatches}`
        : "unknown",
    ],
  ];
}

export function EvaluationPage() {
  const { token } = useToken();
  const query = useQuery({
    queryKey: ["evaluation-summary"],
    queryFn: () => getEvaluationSummary(token as string),
    enabled: Boolean(token),
    staleTime: 60_000,
  });
  const summary = query.data ?? FALLBACK;
  const chartIsJudgeMeans = Boolean(summary.judge?.measured && summary.judge.chart?.length);
  const chartPoints = chartIsJudgeMeans
    ? (summary.judge?.chart ?? [])
    : (summary.deterministic?.chart ?? []);
  const title = summary.judge?.measured
    ? "Offline evaluation snapshot"
    : "Offline harness results (LLM judge not measured)";

  return (
    <section className="stack">
      <PageHeader title={title} lede={summary.judge?.note || summary.deterministic?.note || ""} />
      <p className="meta" role="status">
        Guests cannot launch benchmarks from this demo. Figures below are the published offline
        harness note, not a live scoreboard.
      </p>
      {query.isError ? (
        <p className="meta" role="status">
          Live summary unavailable; showing the bundled publish.
        </p>
      ) : null}
      <ScoreChart
        points={chartPoints}
        valueKind={chartIsJudgeMeans ? "mean_score" : "fixture_runs"}
      />
      <div className="table-wrap panel">
        <table>
          <caption className="meta">Evaluation metrics</caption>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {metricRows(summary).map((row) => (
              <tr key={row.metric}>
                <th scope="row">{row.metric}</th>
                <td>{row.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-wrap panel">
        <table>
          <caption className="meta">Benchmark metadata</caption>
          <tbody>
            {metadataRows(summary).map(([label, value]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {summary.deterministic?.rows?.length ? (
        <div className="table-wrap panel">
          <table>
            <caption className="meta">Deterministic fixture rows</caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Case</th>
                <th scope="col">Codes</th>
                <th scope="col">Matched</th>
              </tr>
            </thead>
            <tbody>
              {summary.deterministic.rows.map((row) => (
                <tr key={row.run_id}>
                  <th scope="row">{row.run_id}</th>
                  <td>{row.case_id}</td>
                  <td>{row.issue_codes.length ? row.issue_codes.join(", ") : "pass"}</td>
                  <td>
                    {row.matched_expectation === null
                      ? "n/a"
                      : row.matched_expectation
                        ? "yes"
                        : "no"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export type ScoreChartValueKind = "mean_score" | "fixture_runs";

/** Judge chart points are 0–1 means; deterministic charts are integer fixture counts. */
export function ScoreChart({
  points,
  valueKind = "fixture_runs",
}: {
  points: { label: string; count: number }[];
  valueKind?: ScoreChartValueKind;
}) {
  if (points.length === 0) return <p>No score series to chart.</p>;
  const seriesName = valueKind === "mean_score" ? "mean score (0–1)" : "fixture runs";
  const allowDecimals = valueKind === "mean_score";
  return (
    <div
      className="panel h-56"
      data-testid="score-chart"
      data-value-kind={valueKind}
      aria-label={seriesName}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={points}>
          <XAxis dataKey="label" />
          <YAxis
            allowDecimals={allowDecimals}
            domain={valueKind === "mean_score" ? [0, 1] : undefined}
          />
          <Tooltip />
          <Bar dataKey="count" fill="#0f4f66" name={seriesName} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
