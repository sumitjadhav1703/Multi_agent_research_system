import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { MarkdownView } from "./MarkdownView";

describe("MarkdownView", () => {
  it("renders citation links and does not create raw HTML elements", () => {
    const { container } = render(
      <MemoryRouter>
        <MarkdownView
          markdown={"Finding <script>alert(1)</script> and <img src=x onerror=alert(1)> cites ev_sq1_1."}
          citationIds={["ev_sq1_1"]}
          allowedUrls={["https://example.test/transit"]}
          runId="run-1"
        />
      </MemoryRouter>,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: "ev_sq1_1" })).toHaveAttribute(
      "href",
      "/runs/run-1/evidence?passage=ev_sq1_1",
    );
  });

  it("renders markdown images only for allowlisted http(s) URLs", () => {
    const { container } = render(
      <MemoryRouter>
        <MarkdownView
          markdown={"Safe ![ok](https://example.test/transit) and bad ![x](https://attacker.example/p)"}
          citationIds={[]}
          allowedUrls={["https://example.test/transit"]}
          runId="run-1"
        />
      </MemoryRouter>,
    );
    const images = container.querySelectorAll("img");
    expect(images).toHaveLength(1);
    expect(images[0]?.getAttribute("src")).toBe("https://example.test/transit");
    expect(container.textContent).toContain("x");
  });
});
