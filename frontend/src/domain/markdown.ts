export function neutralizeHtml(markdown: string): string {
  return markdown.replace(/</g, "&lt;");
}

export function linkCitations(markdown: string, ids: readonly string[]): string {
  const unique = [...new Set(ids.filter((id) => id.length > 0))].sort((left, right) => right.length - left.length);
  let output = markdown;
  for (const id of unique) {
    const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(`(^|[^\\w-])(${escaped})(?=$|[^\\w-])`, "g");
    output = output.replace(pattern, (_match, prefix: string, found: string) => {
      return `${prefix}[${found}](#cite-${encodeURIComponent(found)})`;
    });
  }
  return output;
}

export function citationIdsFrom(ids: readonly string[]): string[] {
  return [...new Set(ids)];
}
