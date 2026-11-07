import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createRun, getUsage } from "../api/client";
import { rememberRun, useToken } from "../auth/token";
import { ErrorText, PageHeader } from "../components/ui";

const EXAMPLES = [
  "What public sources disagree about winter peak demand from heat pumps?",
  "Which public documents describe EU battery recycling rules since 2023?",
  "What published evidence compares small modular reactor cost estimates?",
];

const LIMIT_LABELS: Record<string, string> = {
  max_subquestions: "Subquestions",
  max_parallel_workers: "Parallel workers",
  max_sources: "Sources",
  max_search_calls: "Search calls",
  max_evidence_retries: "Evidence retries",
  max_revisions: "Revisions",
  max_model_calls: "Model calls",
  max_wall_clock_seconds: "Max run time (seconds)",
};

export function NewResearchPage() {
  const { token } = useToken();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [topic, setTopic] = useState("");
  const idempotencyKey = useRef<string | null>(null);
  const usage = useQuery({
    queryKey: ["usage"],
    enabled: Boolean(token),
    queryFn: () => getUsage(token as string),
  });
  const mutation = useMutation({
    mutationFn: (value: string) => {
      const key = idempotencyKey.current ?? crypto.randomUUID();
      idempotencyKey.current = key;
      return createRun(token as string, value, key);
    },
    onSuccess: async (run) => {
      idempotencyKey.current = null;
      rememberRun(run.run_id);
      await queryClient.invalidateQueries({ queryKey: ["usage"] });
      navigate(`/runs/${run.run_id}`, { state: { reused: Boolean(run.reused) } });
    },
  });

  useEffect(() => {
    idempotencyKey.current = null;
  }, [topic]);

  const data = usage.data;
  const blockedReason = blockReason(topic, data, usage.isPending, usage.isError);
  const runs = data?.run_ids ?? [];

  return (
    <section className="stack">
      <PageHeader
        eyebrow="New research"
        title="Ask one public question"
        lede="One research run per guest token for this demo. Submit only public, non-sensitive topics. Free provider APIs receive the question."
      />
      <p className="banner info" role="status">
        One research run per account for this demo. {data?.note ?? "Checking the allowance."}
      </p>
      {data?.one_use_consumed ? (
        <div className="banner warning" role="status">
          <h2>Quota consumed</h2>
          <p>This guest identity has already used its research run. Reopen the saved run instead of starting another.</p>
          <div className="button-row">
            {runs.map((runId) => (
              <Link key={runId} to={`/runs/${runId}`}>
                Reopen existing run
              </Link>
            ))}
          </div>
        </div>
      ) : null}
      {data?.one_use_refunded && !data.one_use_consumed ? (
        <p className="banner info" role="status">
          The previous attempt was refunded before provider work. One run is available.
        </p>
      ) : null}
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (blockedReason) return;
          mutation.mutate(topic.trim());
        }}
      >
        <label className="field">
          <span>Research question</span>
          <textarea
            name="topic"
            maxLength={500}
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
          />
        </label>
        <p className="meta">{topic.trim().length} / 500</p>
        <div className="button-row">
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="secondary" onClick={() => setTopic(example)}>
              {example}
            </button>
          ))}
        </div>
        <details className="panel">
          <summary>Server budgets</summary>
          <p>
            Depth, source cap, and citation handling are fixed by the server. This form cannot raise them.
            Citation markers open the saved evidence item.
          </p>
          <dl className="metric-list">
            {Object.entries(LIMIT_LABELS).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{data?.limits?.[key] ?? "unknown"}</dd>
              </div>
            ))}
          </dl>
        </details>
        {blockedReason ? <p role="status">{blockedReason}</p> : null}
        <ErrorText error={mutation.error} />
        <button type="submit" disabled={Boolean(blockedReason) || mutation.isPending}>
          {mutation.isPending ? "Starting…" : "Start research"}
        </button>
      </form>
    </section>
  );
}

function blockReason(
  topic: string,
  usage: { one_use_consumed: boolean; global_active_runs: number; global_max_active_runs: number; global_daily_starts: number; global_daily_cap: number } | undefined,
  pending: boolean,
  failed: boolean,
): string | null {
  if (pending) return "Checking the demo allowance.";
  if (failed || !usage) return "The allowance could not be loaded. Start stays off until the server answers.";
  if (usage.one_use_consumed) return "The one-use allowance is already consumed.";
  if (usage.global_active_runs >= usage.global_max_active_runs) {
    return "The demo already has the maximum number of active runs.";
  }
  if (usage.global_daily_starts >= usage.global_daily_cap) return "The demo has reached its daily run cap.";
  if (topic.trim().length === 0) return "Enter a research question.";
  if (topic.trim().length > 500) return "The question must be 500 characters or fewer.";
  return null;
}
