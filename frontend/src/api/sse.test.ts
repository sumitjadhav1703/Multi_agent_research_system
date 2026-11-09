import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: vi.fn(),
}));

import { fetchEventSource } from "@microsoft/fetch-event-source";
import { consumeRunStream, type StreamHandlers } from "./sse";

type StreamInit = {
  headers?: Record<string, string>;
  onopen?: (response: Response) => Promise<void> | void;
  onmessage?: (message: { event?: string; data?: string }) => void;
  onerror?: (error: unknown) => number | void;
};

function handlers(signal: AbortSignal, after = 0): StreamHandlers {
  return {
    token: "guest-token-value",
    runId: "run-1",
    after,
    signal,
    onOpen: () => undefined,
    onEvent: () => undefined,
    onSnapshot: () => undefined,
    onClosed: () => undefined,
    onUnauthorized: () => undefined,
    onDrop: () => undefined,
  };
}

describe("run stream", () => {
  beforeEach(() => {
    vi.mocked(fetchEventSource).mockReset();
  });

  it("sends Last-Event-ID only after a cursor and keeps the token out of the URL", async () => {
    const seen: { url: string; lastEventId?: string; authorization?: string }[] = [];
    vi.mocked(fetchEventSource).mockImplementation(async (url, options) => {
      const init = options as StreamInit;
      seen.push({
        url: String(url),
        lastEventId: init.headers?.["last-event-id"],
        authorization: init.headers?.Authorization,
      });
      init.onmessage?.({ event: "stream.closed", data: JSON.stringify({ status: "completed" }) });
    });

    await consumeRunStream(handlers(new AbortController().signal, 0));
    await consumeRunStream(handlers(new AbortController().signal, 7));

    expect(seen).toHaveLength(2);
    expect(seen[0]?.lastEventId).toBeUndefined();
    expect(seen[1]?.lastEventId).toBe("7");
    expect(seen[0]?.authorization).toBe("Bearer guest-token-value");
    expect(seen[0]?.url).not.toMatch(/token|authorization|guest-token/i);
    expect(seen[1]?.url).not.toMatch(/token|authorization|guest-token/i);
  });

  it("reconnects from the highest applied sequence", async () => {
    vi.useFakeTimers();
    const cursors: Array<string | undefined> = [];
    let calls = 0;
    vi.mocked(fetchEventSource).mockImplementation(async (_url, options) => {
      const init = options as StreamInit;
      calls += 1;
      cursors.push(init.headers?.["last-event-id"]);
      if (calls === 1) {
        init.onmessage?.({
          event: "worker.done",
          data: JSON.stringify({
            sequence_id: 1,
            type: "worker.done",
            payload: {},
            created_at: "2026-11-09T00:00:00Z",
          }),
        });
        init.onmessage?.({
          event: "evidence.stored",
          data: JSON.stringify({
            sequence_id: 4,
            type: "evidence.stored",
            payload: {},
            created_at: "2026-11-09T00:00:01Z",
          }),
        });
        init.onerror?.(new Error("drop"));
        return;
      }
      await init.onopen?.(new Response(null, { status: 401, headers: { "content-type": "application/json" } }));
    });

    const pending = consumeRunStream(handlers(new AbortController().signal, 2));
    await vi.advanceTimersByTimeAsync(1600);
    await pending;

    expect(cursors[0]).toBe("2");
    expect(cursors[1]).toBe("4");
    vi.useRealTimers();
  });

  it("stops on 401 and reports unauthorized", async () => {
    const result = await driveStream((init) =>
      init.onopen?.(new Response(null, { status: 401, headers: { "content-type": "application/json" } })),
    );
    expect(result.calls).toBe(1);
    expect(result.onUnauthorized).toHaveBeenCalledTimes(1);
    expect(result.onClosed).not.toHaveBeenCalled();
  });

  it("stops on 404 without retrying", async () => {
    const result = await driveStream((init) =>
      init.onopen?.(new Response(null, { status: 404, headers: { "content-type": "application/json" } })),
    );
    expect(result.calls).toBe(1);
    expect(result.onUnauthorized).not.toHaveBeenCalled();
  });

  it("retries a non-stream 502 and a plain 200", async () => {
    const gateway = await driveStream((init) =>
      init.onopen?.(new Response(null, { status: 502, headers: { "content-type": "text/plain" } })),
    );
    expect(gateway.calls).toBeGreaterThan(1);
    expect(gateway.onDrop).toHaveBeenCalled();

    const page = await driveStream((init) =>
      init.onopen?.(new Response(null, { status: 200, headers: { "content-type": "text/html" } })),
    );
    expect(page.calls).toBeGreaterThan(1);
    expect(page.onClosed).not.toHaveBeenCalled();
  });

  it("retries when stream.closed is unavailable or missing a status", async () => {
    const unavailable = await driveStream((init) => {
      init.onmessage?.({ event: "stream.closed", data: JSON.stringify({ status: "unavailable" }) });
    });
    expect(unavailable.calls).toBeGreaterThan(1);
    expect(unavailable.onClosed).not.toHaveBeenCalled();
    expect(unavailable.onDrop).toHaveBeenCalled();

    const missing = await driveStream((init) => {
      init.onmessage?.({ event: "stream.closed", data: JSON.stringify({}) });
    });
    expect(missing.calls).toBeGreaterThan(1);
    expect(missing.onClosed).not.toHaveBeenCalled();
  });

  it("finishes when stream.closed status is rejected", async () => {
    const result = await driveStream((init) => {
      init.onmessage?.({ event: "stream.closed", data: JSON.stringify({ status: "rejected" }) });
    });
    expect(result.calls).toBe(1);
    expect(result.onClosed).toHaveBeenCalledTimes(1);
  });
});

async function driveStream(open: (init: StreamInit) => Promise<void> | void) {
  vi.useFakeTimers();
  const controller = new AbortController();
  let calls = 0;
  const onClosed = vi.fn();
  const onUnauthorized = vi.fn();
  const onDrop = vi.fn();
  try {
    vi.mocked(fetchEventSource).mockImplementation(async (_url, options) => {
      const init = options as StreamInit;
      calls += 1;
      if (calls > 1) {
        controller.abort();
        return;
      }
      await open(init);
    });
    const pending = consumeRunStream({
      ...handlers(controller.signal),
      onClosed,
      onUnauthorized,
      onDrop,
    });
    await vi.advanceTimersByTimeAsync(2000);
    await pending;
    return { calls, onClosed, onUnauthorized, onDrop };
  } finally {
    vi.useRealTimers();
  }
}
