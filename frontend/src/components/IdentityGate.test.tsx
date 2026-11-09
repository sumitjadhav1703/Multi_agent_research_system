import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createGuest } from "../api/client";
import { TokenProvider } from "../auth/token";
import { IdentityGate } from "./IdentityGate";

vi.mock("../api/client", () => ({
  createGuest: vi.fn(),
  readEnv: (name: string) => (name === "VITE_TURNSTILE_SITE_KEY" ? "site-key" : ""),
}));

interface CapturedWidget {
  callback: (token: string) => void;
  "expired-callback"?: () => void;
  "error-callback"?: () => void;
}

describe("IdentityGate", () => {
  const reset = vi.fn();
  let captured: CapturedWidget | undefined;

  beforeEach(() => {
    captured = undefined;
    reset.mockReset();
    vi.mocked(createGuest).mockReset();
    window.turnstile = {
      render: (_node, options) => {
        captured = options;
        return "widget-1";
      },
      reset,
    };
  });

  afterEach(() => {
    delete window.turnstile;
  });

  function renderGate() {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
      <QueryClientProvider client={client}>
        <TokenProvider>
          <IdentityGate />
        </TokenProvider>
      </QueryClientProvider>,
    );
  }

  async function issueToken(token: string) {
    renderGate();
    await waitFor(() => expect(captured).toBeTruthy());
    act(() => {
      captured?.callback(token);
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
  }

  it("clears the token and resets Turnstile when the challenge expires or errors", async () => {
    await issueToken("spent-token");

    act(() => {
      captured?.["expired-callback"]?.();
    });
    expect(reset).toHaveBeenCalledWith("widget-1");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();

    act(() => {
      captured?.callback("again");
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
    act(() => {
      captured?.["error-callback"]?.();
    });
    expect(reset).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("clears the token and resets Turnstile when guest creation fails", async () => {
    vi.mocked(createGuest).mockRejectedValue(new Error("Verification was rejected"));
    await issueToken("spent-token");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Verification was rejected");
    expect(reset).toHaveBeenCalledWith("widget-1");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(createGuest).toHaveBeenCalledWith("spent-token");
  });
});
