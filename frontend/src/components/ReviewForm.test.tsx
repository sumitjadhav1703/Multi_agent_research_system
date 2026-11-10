import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TokenProvider } from "../auth/token";
import { ReviewForm } from "./ReviewForm";

function renderForm(canRevise: boolean) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TokenProvider>
        <ReviewForm runId="run-1" canRevise={canRevise} />
      </TokenProvider>
    </QueryClientProvider>,
  );
}

describe("ReviewForm", () => {
  it("offers the revision only while it is unused", () => {
    renderForm(true);
    expect(screen.getByRole("button", { name: "Request one revision" })).toBeInTheDocument();
  });

  it("hides the revision button once used but keeps approve and reject", () => {
    renderForm(false);
    expect(screen.queryByRole("button", { name: "Request one revision" })).toBeNull();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });
});
