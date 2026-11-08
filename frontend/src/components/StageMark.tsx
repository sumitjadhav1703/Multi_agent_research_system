/** Pixel geometry marks for process-rail stages. Theme-native; no emoji. */
export type StageMarkKind =
  | "plan"
  | "workers"
  | "sources"
  | "evidence"
  | "verify"
  | "report"
  | "review";

const TITLES: Record<StageMarkKind, string> = {
  plan: "Plan",
  workers: "Workers",
  sources: "Sources",
  evidence: "Evidence",
  verify: "Verify",
  report: "Report",
  review: "Review",
};

export function StageMark({
  kind,
  className = "",
}: {
  kind: StageMarkKind;
  className?: string;
}) {
  return (
    <svg
      className={`stage-mark ${className}`.trim()}
      width="20"
      height="20"
      viewBox="0 0 20 20"
      aria-hidden="true"
      focusable="false"
    >
      <title>{TITLES[kind]}</title>
      {kind === "plan" ? (
        <>
          <rect x="3" y="3" width="14" height="2" fill="currentColor" />
          <rect x="3" y="8" width="10" height="2" fill="currentColor" />
          <rect x="3" y="13" width="12" height="2" fill="currentColor" />
          <rect x="15" y="8" width="2" height="2" fill="currentColor" />
        </>
      ) : null}
      {kind === "workers" ? (
        <>
          <rect x="2" y="4" width="6" height="6" fill="currentColor" />
          <rect x="12" y="4" width="6" height="6" fill="currentColor" />
          <rect x="7" y="12" width="6" height="5" fill="currentColor" opacity="0.75" />
        </>
      ) : null}
      {kind === "sources" ? (
        <>
          <rect x="4" y="2" width="12" height="3" fill="currentColor" />
          <rect x="4" y="8" width="12" height="3" fill="currentColor" opacity="0.7" />
          <rect x="4" y="14" width="12" height="3" fill="currentColor" opacity="0.4" />
        </>
      ) : null}
      {kind === "evidence" ? (
        <>
          <rect x="3" y="3" width="14" height="14" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <rect x="6" y="7" width="8" height="2" fill="currentColor" />
          <rect x="6" y="11" width="5" height="2" fill="currentColor" />
        </>
      ) : null}
      {kind === "verify" ? (
        <>
          <rect x="3" y="3" width="14" height="14" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <rect x="6" y="9" width="3" height="2" fill="currentColor" />
          <rect x="9" y="11" width="2" height="2" fill="currentColor" />
          <rect x="11" y="5" width="2" height="6" fill="currentColor" transform="rotate(45 12 8)" />
        </>
      ) : null}
      {kind === "report" ? (
        <>
          <rect x="4" y="2" width="12" height="16" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <rect x="7" y="5" width="6" height="2" fill="currentColor" />
          <rect x="7" y="9" width="6" height="2" fill="currentColor" />
          <rect x="7" y="13" width="4" height="2" fill="currentColor" />
        </>
      ) : null}
      {kind === "review" ? (
        <>
          <rect x="2" y="5" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <rect x="8" y="3" width="10" height="10" fill="currentColor" opacity="0.35" />
          <rect x="10" y="7" width="4" height="2" fill="currentColor" />
        </>
      ) : null}
    </svg>
  );
}

export function stageMarkKind(id: string): StageMarkKind {
  switch (id) {
    case "plan":
    case "workers":
    case "sources":
    case "evidence":
    case "verify":
    case "report":
    case "review":
      return id;
    default:
      return "plan";
  }
}
