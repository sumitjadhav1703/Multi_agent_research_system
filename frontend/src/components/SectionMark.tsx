/** Theme-native monochrome marks (pixel geometry). No emoji. */
export type SectionMarkKind = "answer" | "critics" | "sources" | "flow";

const TITLES: Record<SectionMarkKind, string> = {
  answer: "Answer",
  critics: "Critics",
  sources: "Sources",
  flow: "Process",
};

export function SectionMark({
  kind,
  className = "",
}: {
  kind: SectionMarkKind;
  className?: string;
}) {
  return (
    <svg
      className={`section-mark ${className}`.trim()}
      width="18"
      height="18"
      viewBox="0 0 18 18"
      aria-hidden="true"
      focusable="false"
    >
      <title>{TITLES[kind]}</title>
      {kind === "answer" ? (
        <>
          <rect x="2" y="2" width="14" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <rect x="5" y="5" width="8" height="2" fill="currentColor" />
          <rect x="5" y="9" width="8" height="2" fill="currentColor" />
          <rect x="5" y="13" width="5" height="2" fill="currentColor" />
        </>
      ) : null}
      {kind === "critics" ? (
        <>
          <rect x="3" y="3" width="5" height="5" fill="currentColor" />
          <rect x="10" y="3" width="5" height="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <rect x="3" y="10" width="5" height="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <rect x="10" y="10" width="5" height="5" fill="currentColor" />
        </>
      ) : null}
      {kind === "sources" ? (
        <>
          <rect x="3" y="2" width="12" height="3" fill="currentColor" />
          <rect x="3" y="7.5" width="12" height="3" fill="currentColor" opacity="0.7" />
          <rect x="3" y="13" width="12" height="3" fill="currentColor" opacity="0.4" />
        </>
      ) : null}
      {kind === "flow" ? (
        <>
          <rect x="2" y="7" width="4" height="4" fill="currentColor" />
          <rect x="7" y="8" width="2" height="2" fill="currentColor" />
          <rect x="10" y="7" width="4" height="4" fill="currentColor" />
          <rect x="15" y="8" width="1" height="2" fill="currentColor" />
        </>
      ) : null}
    </svg>
  );
}

export function SectionHeading({
  kind,
  children,
}: {
  kind: SectionMarkKind;
  children: string;
}) {
  return (
    <h2 className="section-heading">
      <SectionMark kind={kind} />
      <span>{children}</span>
    </h2>
  );
}
