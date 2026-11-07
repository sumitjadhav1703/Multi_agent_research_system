import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";
import { ApiError, getEvents, getRun } from "../api/client";
import { consumeRunStream } from "../api/sse";
import { useToken } from "../auth/token";
import { maxSequence, TERMINAL_STATUSES } from "../domain/runView";
import { runStore } from "../state/runStore";

export function useRunChannel(runId: string | undefined) {
  const { token, clearToken } = useToken();
  const queryClient = useQueryClient();
  const version = useSyncExternalStore(runStore.subscribe, runStore.getVersion, runStore.getVersion);
  const entry = runId ? runStore.get(runId) : undefined;
  void version;

  const runQuery = useQuery({
    queryKey: ["run", runId],
    enabled: Boolean(token && runId),
    queryFn: () => getRun(token as string, runId as string),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || TERMINAL_STATUSES.has(status)) return false;
      return entry?.connection === "live" ? 8000 : 3000;
    },
  });

  const eventsQuery = useQuery({
    queryKey: ["events", runId, "seed"],
    enabled: Boolean(token && runId),
    staleTime: Infinity,
    queryFn: () => getEvents(token as string, runId as string, 0),
  });

  useEffect(() => {
    if (!runId || !eventsQuery.data) return;
    runStore.merge(runId, eventsQuery.data.events);
  }, [runId, eventsQuery.data]);

  useEffect(() => {
    if (runQuery.error instanceof ApiError && runQuery.error.status === 401) clearToken();
    if (eventsQuery.error instanceof ApiError && eventsQuery.error.status === 401) clearToken();
  }, [runQuery.error, eventsQuery.error, clearToken]);

  useEffect(() => {
    if (!runId || !token || eventsQuery.isLoading) return;
    const controller = new AbortController();
    const after = maxSequence(runStore.get(runId)?.events ?? []);
    runStore.setConnection(runId, "reconnecting");
    void consumeRunStream({
      token,
      runId,
      after,
      signal: controller.signal,
      onOpen: () => runStore.setConnection(runId, "live"),
      onEvent: (event) => runStore.merge(runId, [event]),
      onSnapshot: (snapshot) => runStore.setSnapshot(runId, snapshot),
      onClosed: () => {
        runStore.setConnection(runId, "closed");
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
      },
      onUnauthorized: () => clearToken(),
      onDrop: () => {
        runStore.setConnection(runId, "reconnecting");
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
      },
    });
    return () => controller.abort();
  }, [runId, token, eventsQuery.isLoading, clearToken, queryClient]);

  useEffect(() => {
    if (!runId) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [runId, queryClient]);

  return {
    runQuery,
    eventsQuery,
    events: entry?.events ?? [],
    snapshot: entry?.snapshot ?? null,
    connection: entry?.connection ?? "idle",
  };
}
