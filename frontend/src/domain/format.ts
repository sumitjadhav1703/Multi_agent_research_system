export function formatUnknown(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "unknown";
  return String(value);
}

/** List-price USD estimate from the API (token×rate). Keep "unknown" when absent. */
export function formatCostUsd(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "unknown";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `$${num.toFixed(6)}`;
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

export function formatElapsed(start: string | null, end: string | null, now = Date.now()): string {
  if (!start) return "not started";
  const opened = Date.parse(start);
  if (Number.isNaN(opened)) return "unknown";
  const closed = end ? Date.parse(end) : now;
  if (Number.isNaN(closed)) return "unknown";
  const seconds = Math.max(0, Math.round((closed - opened) / 1000));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes > 0) return `${minutes}m ${rest}s`;
  return `${rest}s`;
}

export function extractionLabel(method: string): string {
  switch (method) {
    case "html":
      return "Full page text";
    case "snippet":
      return "Search snippet only";
    case "unsupported_pdf":
      return "PDF was not parsed";
    case "failed":
      return "Extraction failed";
    default:
      return method || "unknown";
  }
}
