import type { ArtifactSnapshot, RunEvent } from "./types";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { streamUrl } from "./client";

export interface StreamHandlers {
  token: string;
  runId: string;
  after: number;
  signal: AbortSignal;
  onOpen: () => void;
  onEvent: (event: RunEvent) => void;
  onSnapshot: (snapshot: ArtifactSnapshot) => void;
  onClosed: () => void;
  onUnauthorized: () => void;
  onDrop: () => void;
}

export async function consumeRunStream(options: StreamHandlers): Promise<void> {
  let cursor = options.after;
  while (!options.signal.aborted) {
    let finished = false;
    let stop = false;
    try {
      await fetchEventSource(streamUrl(options.runId), {
        method: "GET",
        signal: options.signal,
        openWhenHidden: true,
        headers: streamHeaders(options.token, cursor),
        async onopen(response) {
          const type = response.headers.get("content-type") ?? "";
          if (response.ok && type.includes("text/event-stream")) {
            options.onOpen();
            return;
          }
          if (response.status === 401) options.onUnauthorized();
          stop = true;
          throw new Error(`stream ${response.status}`);
        },
        onmessage(message) {
          if (!message.data || message.event === "heartbeat") return;
          let parsed: unknown;
          try {
            parsed = JSON.parse(message.data);
          } catch {
            return;
          }
          if (message.event === "snapshot" && parsed && typeof parsed === "object") {
            options.onSnapshot(parsed as ArtifactSnapshot);
            return;
          }
          if (message.event === "stream.closed") {
            finished = true;
            options.onClosed();
            return;
          }
          if (!parsed || typeof parsed !== "object") return;
          const event = parsed as RunEvent;
          if (typeof event.sequence_id !== "number" || typeof event.type !== "string") return;
          cursor = Math.max(cursor, event.sequence_id);
          options.onEvent(event);
        },
        onerror(error) {
          if (finished || stop || options.signal.aborted) {
            throw error instanceof Error ? error : new Error("stream stopped");
          }
          options.onDrop();
          return 1500;
        },
      });
    } catch {
      if (options.signal.aborted || finished || stop) return;
      options.onDrop();
    }
    if (finished || options.signal.aborted || stop) return;
    options.onDrop();
    await wait(1500, options.signal);
  }
}

function streamHeaders(token: string, cursor: number): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: "text/event-stream",
  };
  if (cursor > 0) headers["last-event-id"] = String(cursor);
  return headers;
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}
