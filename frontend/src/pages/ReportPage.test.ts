import { describe, expect, it, vi } from "vitest";
import { downloadMarkdown } from "./ReportPage";

describe("downloadMarkdown", () => {
  it("downloads the report text as a markdown blob, not a screenshot", () => {
    const click = vi.fn();
    const createElement = vi.spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "a") {
        return { click, download: "", href: "" } as unknown as HTMLAnchorElement;
      }
      return document.createElementNS("http://www.w3.org/1999/xhtml", tag);
    });
    let captured: Blob | undefined;
    const createObjectURL = vi.fn((value: Blob | MediaSource) => {
      if (value instanceof Blob) captured = value;
      return "blob:test";
    });
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

    const body = "# Answer\n\nProvisional notes about SMR costs.";
    downloadMarkdown("run-1", body);

    // #region agent log
    fetch("http://127.0.0.1:7852/ingest/121a75ee-5e4a-4dda-bdc0-1f16831db8ba", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "003bae" },
      body: JSON.stringify({
        sessionId: "003bae",
        runId: "post-fix",
        hypothesisId: "A",
        location: "ReportPage.test.ts:downloadMarkdown",
        message: "blob capture after downloadMarkdown",
        data: {
          called: createObjectURL.mock.calls.length,
          blobType: captured?.type ?? null,
          clicked: click.mock.calls.length,
        },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(captured).toBeInstanceOf(Blob);
    expect(captured?.type).toBe("text/markdown;charset=utf-8");
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test");

    createElement.mockRestore();
    vi.unstubAllGlobals();
  });
});
