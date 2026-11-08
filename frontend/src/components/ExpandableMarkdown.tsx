import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { MarkdownView } from "./MarkdownView";

/** Line-clamp preview with View more / View less (WhatsApp-style). */
export function ExpandableMarkdown({
  markdown,
  citationIds,
  allowedUrls,
  runId,
  lines = 6,
  className = "",
}: {
  markdown: string;
  citationIds: string[];
  allowedUrls: string[];
  runId: string;
  lines?: number;
  className?: string;
}) {
  const regionId = useId();
  const bodyRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const node = bodyRef.current;
    if (!node || expanded) return;
    const measure = () => {
      setOverflows(node.scrollHeight > node.clientHeight + 2);
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [markdown, lines, expanded]);

  const showToggle = overflows || expanded;

  return (
    <div className={`expandable-md ${className}`.trim()}>
      <div
        id={regionId}
        ref={bodyRef}
        className={`expandable-md-body${expanded ? " is-open" : " is-preview"}${
          overflows && !expanded ? " has-fade" : ""
        }`}
        style={expanded ? undefined : ({ "--clamp-lines": lines } as CSSProperties)}
      >
        <MarkdownView markdown={markdown} citationIds={citationIds} allowedUrls={allowedUrls} runId={runId} />
      </div>
      {showToggle ? (
        <button
          type="button"
          className="text-toggle"
          aria-expanded={expanded}
          aria-controls={regionId}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "View less" : "View more"}
          <span className="visually-hidden"> of the answer</span>
        </button>
      ) : null}
    </div>
  );
}
