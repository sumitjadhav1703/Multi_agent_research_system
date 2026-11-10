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

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(captured).toBeInstanceOf(Blob);
    expect(captured?.type).toBe("text/markdown;charset=utf-8");
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test");

    createElement.mockRestore();
    vi.unstubAllGlobals();
  });
});
