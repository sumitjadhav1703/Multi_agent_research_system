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
        title="Ask one public question"
        lede="One research run for this guest session. Keep topics public and non-sensitive."
      />

      {data?.one_use_consumed ? (
        <div className="banner warning" role="status">
          <h2>Your demo run is used</h2>
          <p>Open the saved run instead of starting another.</p>
          <div className="button-row">
            {runs.map((runId) => (
              <Link key={runId} className="button" to={`/runs/${runId}`}>
                Open run
              </Link>
            ))}
          </div>
        </div>
      ) : (
        <p className="meta" role="status">
          {data?.note ?? "Checking allowance…"}
        </p>
      )}

      {data?.one_use_refunded && !data.one_use_consumed ? (
        <p className="banner info" role="status">
          Previous attempt was refunded. You still have one run.
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
            placeholder="Type a research question…"
          />
        </label>
        <p className="meta">{topic.trim().length} / 500</p>
        <div className="chip-row">
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="chip" onClick={() => setTopic(example)}>
              {example}
            </button>
          ))}
        </div>
        <details className="details-panel">
          <summary>Server limits</summary>
          <p>These caps are fixed by the server for the demo.</p>
          <dl className="metric-list">
            {Object.entries(LIMIT_LABELS).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{data?.limits?.[key] ?? "—"}</dd>
              </div>
            ))}
          </dl>
        </details>
        {blockedReason ? <p className="meta" role="status">{blockedReason}</p> : null}
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
  usage:
    | {
        one_use_consumed: boolean;
        global_active_runs: number;
        global_max_active_runs: number;
        global_daily_starts: number;
        global_daily_cap: number;
      }
    | undefined,
  pending: boolean,
  failed: boolean,
): string | null {
  if (pending) return "Checking allowance…";
  if (failed || !usage) return "Allowance unavailable. Start stays off until the server answers.";
  if (usage.one_use_consumed) return "Demo run already used.";
  if (usage.global_active_runs >= usage.global_max_active_runs) {
    return "Demo already has the maximum active runs.";
  }
  if (usage.global_daily_starts >= usage.global_daily_cap) return "Daily demo cap reached.";
  if (topic.trim().length === 0) return "Enter a research question.";
  if (topic.trim().length > 500) return "Keep the question to 500 characters.";
  return null;
}
