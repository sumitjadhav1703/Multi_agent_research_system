import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runStore } from "../state/runStore";
import { CURRENT_RUN_KEY, GUEST_TOKEN_KEY, TokenProvider, rememberRun, useToken } from "./token";

describe("token discovery", () => {
  it("clearToken removes the remembered run as well as the guest token", () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "guest-token");
    rememberRun("run-9");
    const queryClient = new QueryClient();
    queryClient.setQueryData(["run", "run-9"], { run_id: "run-9" });
    runStore.setConnection("run-9", "live");

    const { result } = renderHook(() => useToken(), {
      wrapper: ({ children }: { children: ReactNode }) =>
        createElement(QueryClientProvider, { client: queryClient }, createElement(TokenProvider, null, children)),
    });
    act(() => {
      result.current.clearToken();
    });

    expect(sessionStorage.getItem(GUEST_TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(CURRENT_RUN_KEY)).toBeNull();
    expect(queryClient.getQueryData(["run", "run-9"])).toBeUndefined();
    expect(runStore.get("run-9")).toBeUndefined();
  });
});
