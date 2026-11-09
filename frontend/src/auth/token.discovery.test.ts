import { createElement, type ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CURRENT_RUN_KEY, GUEST_TOKEN_KEY, TokenProvider, rememberRun, useToken } from "./token";

describe("token discovery", () => {
  it("clearToken removes the remembered run as well as the guest token", () => {
    sessionStorage.setItem(GUEST_TOKEN_KEY, "guest-token");
    rememberRun("run-9");

    const { result } = renderHook(() => useToken(), {
      wrapper: ({ children }: { children: ReactNode }) => createElement(TokenProvider, null, children),
    });
    act(() => {
      result.current.clearToken();
    });

    expect(sessionStorage.getItem(GUEST_TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(CURRENT_RUN_KEY)).toBeNull();
  });
});
