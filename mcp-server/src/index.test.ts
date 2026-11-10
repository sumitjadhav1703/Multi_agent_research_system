import { afterEach, expect, it, vi } from "vitest";

import worker from "./index";

afterEach(() => vi.unstubAllGlobals());

it("scheduled pings health/live and swallows errors", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response("ok")).mockRejectedValueOnce(new Error("down"));
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "log").mockImplementation(() => {});
  const pending: Promise<unknown>[] = [];
  const ctx = { waitUntil: (p: Promise<unknown>) => pending.push(p) } as unknown as ExecutionContext;
  const env = { RESEARCHMIND_API_BASE: "https://api.example.test" } as never;
  await worker.scheduled({} as ScheduledController, env, ctx);
  await worker.scheduled({} as ScheduledController, env, ctx);
  await Promise.all(pending);
  expect(String(fetchMock.mock.calls[0][0])).toBe("https://api.example.test/api/v1/health/live");
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
