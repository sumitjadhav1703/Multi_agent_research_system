import { useMemo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { linkCitations } from "../domain/markdown";

export function MarkdownView({
  markdown,
  citationIds,
  allowedUrls,
  runId,
}: {
  markdown: string;
  citationIds: readonly string[];
  allowedUrls: readonly string[];
  runId: string;
}) {
  const source = useMemo(
    () => linkCitations(markdown, citationIds),
    [markdown, citationIds],
  );
  const allowed = useMemo(() => new Set(allowedUrls), [allowedUrls]);
  return (
    <div className="report-body">
      <ReactMarkdown
        urlTransform={(url) => {
          if (url.startsWith("#cite-")) return url;
          if (url.startsWith("https://") || url.startsWith("http://")) return url;
          return "";
        }}
        components={{
          a: ({ href, children }) => renderLink(href, children, runId, allowed),
          img: ({ src, alt }) => renderImage(src, alt, allowed),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

function renderLink(
  href: string | undefined,
  children: ReactNode,
  runId: string,
  allowed: Set<string>,
) {
  if (href?.startsWith("#cite-")) {
    const id = decodeURIComponent(href.slice("#cite-".length));
    const param = id.startsWith("cl") ? "claim" : id.startsWith("src_") ? "source" : "passage";
    return (
      <Link className="citation" to={`/runs/${runId}/evidence?${param}=${encodeURIComponent(id)}`}>
        {id}
      </Link>
    );
  }
  if (href && (href.startsWith("https://") || href.startsWith("http://")) && allowed.has(href)) {
    return (
      <a href={href} rel="noopener noreferrer" target="_blank">
        {children}
      </a>
    );
  }
  return <span>{children}</span>;
}

function renderImage(
  src: string | undefined,
  alt: string | undefined,
  allowed: Set<string>,
) {
  if (
    src &&
    (src.startsWith("https://") || src.startsWith("http://")) &&
    allowed.has(src)
  ) {
    return <img src={src} alt={alt || ""} loading="lazy" />;
  }
  return alt ? <span>{alt}</span> : null;
}
