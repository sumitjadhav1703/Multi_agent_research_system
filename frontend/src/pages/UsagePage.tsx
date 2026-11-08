import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";
import { getEvents, getReady, getRun, getUsage } from "../api/client";
import { consumeRunStream } from "../api/sse";
import { useToken } from "../auth/token";
import { ErrorText, PageHeader, UsageFiguresList } from "../components/ui";
import { formatElapsed, formatUnknown, formatWhen } from "../domain/format";
import { maxSequence, sourcesSeenCount, statusLabel } from "../domain/runView";
import { EMPTY_USAGE } from "../api/types";
import { runStore } from "../state/runStore";

export function UsagePage() {
  const { token } = useToken();
  const usage = useQuery({
    queryKey: ["usage"],
    enabled: Boolean(token),
    queryFn: () => getUsage(token as string),
  });
  const health = useQuery({ queryKey: ["health", "ready"], queryFn: getReady });
  const data = usage.data;
  const capped = Boolean(
    data &&
      (data.global_active_runs >= data.global_max_active_runs || data.global_daily_starts >= data.global_daily_cap),
  );

  return (
    <section className="stack">
      <PageHeader
        title="Your usage"
        lede="Runs for this guest session only."
      />
      {usage.isPending ? <p role="status">Loading usage.</p> : null}
      <ErrorText error={usage.error} />
      {data ? (
        <>
          <p className="banner info">{data.note}</p>
          {data.one_use_consumed ? (
            <p className="banner warning" role="status">
              Quota consumed. Remaining one-use allowance: 0.
            </p>
          ) : (
            <p className="banner ok" role="status">
              Remaining one-use allowance: 1.
            </p>
          )}
          {capped ? (
            <p className="banner warning" role="status">
              Demo cap warning: {data.global_active_runs} of {data.global_max_active_runs} active runs,{" "}
              {data.global_daily_starts} of {data.global_daily_cap} daily starts.
            </p>
          ) : null}
          <UsageFiguresList
            heading="Account usage"
            usage={{ ...EMPTY_USAGE, estimated_cost_usd: data.estimated_cost_usd }}
          />
          <section className="panel">
            <h2>Provider status</h2>
            <p>Service: {health.data?.status ?? "unknown"}</p>
            <p>Database: {health.data?.database ?? "unknown"}</p>
            <p>
              {health.data?.use_mock_provider
                ? "Mock provider is configured."
                : "The server router is configured. This page does not measure provider uptime."}
            </p>
          </section>
          <div className="table-wrap panel">
            <table>
              <caption className="meta">Runs for this guest</caption>
              <thead>
                <tr>
                  <th scope="col">Topic</th>
                  <th scope="col">Status</th>
                  <th scope="col">Started</th>
                  <th scope="col">Duration</th>
                  <th scope="col">Sources seen</th>
                  <th scope="col">Stop reason</th>
                </tr>
              </thead>
              <tbody>
                {data.run_ids.length === 0 ? (
                  <tr>
                    <td colSpan={6}>No runs for this guest.</td>
                  </tr>
                ) : (
                  data.run_ids.map((runId) => <RunRow key={runId} runId={runId} />)
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}

function RunRow({ runId }: { runId: string }) {
  const { token } = useToken();
  const version = useSyncExternalStore(runStore.subscribe, runStore.getVersion, runStore.getVersion);
  void version;
  const run = useQuery({
    queryKey: ["run", runId],
    enabled: Boolean(token),
    queryFn: () => getRun(token as string, runId),
  });
  const events = useQuery({
    queryKey: ["events", runId, "seed"],
    enabled: Boolean(token),
    queryFn: () => getEvents(token as string, runId, 0),
  });

  useEffect(() => {
    if (!token || !events.data) return;
    runStore.merge(runId, events.data.events);
    if (runStore.get(runId)?.snapshot) return;
    const controller = new AbortController();
    void consumeRunStream({
      token,
      runId,
      after: maxSequence(events.data.events),
      signal: controller.signal,
      onOpen: () => undefined,
      onEvent: (event) => runStore.merge(runId, [event]),
      onSnapshot: (snapshot) => runStore.setSnapshot(runId, snapshot),
      onClosed: () => undefined,
      onDrop: () => undefined,
      onUnauthorized: () => undefined,
    });
    return () => controller.abort();
  }, [token, runId, events.data]);

  const item = run.data;
  const entry = runStore.get(runId);
  const eventList = events.data?.events ?? entry?.events ?? [];
  const sources =
    events.data || entry?.snapshot
      ? sourcesSeenCount(eventList, entry?.snapshot?.sources.length)
      : null;
  return (
    <tr>
      <td>
        <Link to={`/runs/${runId}`}>{item?.topic ?? "Loading…"}</Link>
      </td>
      <td>{item ? statusLabel(item.status) : "unknown"}</td>
      <td>{formatWhen(item?.created_at)}</td>
      <td>{item ? formatElapsed(item.started_at, item.finished_at) : "unknown"}</td>
      <td>{sources === null ? "unknown" : sources}</td>
      <td>{item ? (item.stop_reason ?? "none recorded") : formatUnknown(null)}</td>
    </tr>
  );
}
