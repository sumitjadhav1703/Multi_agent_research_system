import { createContext, useContext, useMemo } from "react";
import { Outlet, useParams } from "react-router-dom";
import { useRunChannel } from "./useRunChannel";

type RunChannelValue = ReturnType<typeof useRunChannel>;

const RunChannelContext = createContext<RunChannelValue | null>(null);

/** Owns the SSE channel once for Live / Report / Evidence so tab switches do not reconnect. */
export function RunWorkspace() {
  const { runId } = useParams();
  const { runQuery, eventsQuery, events, snapshot, connection } = useRunChannel(runId);
  const channel = useMemo(
    () => ({ runQuery, eventsQuery, events, snapshot, connection }),
    [runQuery, eventsQuery, events, snapshot, connection],
  );
  return (
    <RunChannelContext.Provider value={channel}>
      <Outlet />
    </RunChannelContext.Provider>
  );
}

export function useRunChannelContext(): RunChannelValue {
  const value = useContext(RunChannelContext);
  if (!value) {
    throw new Error("useRunChannelContext must be used inside RunWorkspace");
  }
  return value;
}
