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

function handlers(signal: AbortSignal): StreamHandlers {
  return {
    token: "guest-token-value",
    runId: "run-1",
    after: 0,
    signal,
    onOpen: () => undefined,
    onEvent: () => undefined,
    onSnapshot: () => undefined,
    onClosed: () => undefined,
    onUnauthorized: () => undefined,
    onDrop: () => undefined,
  };
}

describe("run stream discovery", () => {
  beforeEach(() => {
    vi.mocked(fetchEventSource).mockReset();
  });

  it("retries when the stream opens with 503 instead of stopping permanently", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    let calls = 0;
    try {
      vi.mocked(fetchEventSource).mockImplementation(async (_url, options) => {
        const init = options as StreamInit;
        calls += 1;
        if (calls >= 2) {
          controller.abort();
          return;
        }
        await init.onopen?.(
          new Response(null, { status: 503, headers: { "content-type": "text/plain" } }),
        );
      });

      const pending = consumeRunStream(handlers(controller.signal));
      await vi.advanceTimersByTimeAsync(2000);
      await pending;

      expect(calls).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
