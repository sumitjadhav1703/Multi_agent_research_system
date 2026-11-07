import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { PageHeader } from "../components/ui";

const METRICS = [
  "Faithfulness",
  "Answer relevancy",
  "Contextual precision",
  "Contextual recall",
  "Task completion",
  "Plan adherence",
  "Step efficiency",
  "Citation precision",
  "Invalid citations",
];

const METADATA = [
  ["Dataset version", "unknown"],
  ["Cases", "unknown"],
  ["Evaluator model", "unknown"],
  ["DeepEval version", "unknown"],
  ["Run date", "unknown"],
];

export function EvaluationPage() {
  return (
    <section className="stack">
      <PageHeader
        title="No benchmark yet"
        lede="DeepEval is not in this release. No scores were measured."
      />
      <p className="meta" role="status">
        Guests cannot launch benchmarks from this demo.
      </p>
      <ScoreChart points={[]} />
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
            {METRICS.map((metric) => (
              <tr key={metric}>
                <th scope="row">{metric}</th>
                <td>not measured</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-wrap panel">
        <table>
          <caption className="meta">Benchmark metadata</caption>
          <tbody>
            {METADATA.map(([label, value]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ScoreChart({ points }: { points: { label: string; score: number }[] }) {
  if (points.length === 0) return <p>No score series to chart.</p>;
  return (
    <div className="panel h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={points}>
          <XAxis dataKey="label" />
          <YAxis />
          <Bar dataKey="score" fill="#0f4f66" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
