import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoreChart } from "./EvaluationPage";

describe("Evaluation ScoreChart honesty (post-merge delta)", () => {
  it("labels judge means as mean score (0–1), not fixture runs", () => {
    render(
      <ScoreChart
        valueKind="mean_score"
        points={[
          { label: "faithfulness", count: 0.925 },
          { label: "answer relevancy", count: 0.7 },
        ]}
      />,
    );
    const chart = screen.getByTestId("score-chart");
    expect(chart.getAttribute("data-value-kind")).toBe("mean_score");
    expect(chart.getAttribute("aria-label")).toBe("mean score (0–1)");
  });

  it("keeps deterministic charts labeled as fixture runs", () => {
    render(
      <ScoreChart
        valueKind="fixture_runs"
        points={[
          { label: "pass", count: 3 },
          { label: "fail", count: 1 },
        ]}
      />,
    );
    const chart = screen.getByTestId("score-chart");
    expect(chart.getAttribute("data-value-kind")).toBe("fixture_runs");
    expect(chart.getAttribute("aria-label")).toBe("fixture runs");
  });
});
