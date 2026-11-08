import { useEffect, useId, useState, type ReactNode } from "react";

/** Report-style disclosure: summary toggles the body. */
export function CollapsiblePanel({
  title,
  children,
  defaultOpen = false,
  className = "",
  count,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  count?: number | string | null;
}) {
  const panelId = useId();
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  return (
    <details
      className={`details-panel collapsible-panel ${className}`.trim()}
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
    >
      <summary aria-controls={panelId}>
        <h2 className="collapsible-title">{title}</h2>
        {count != null && count !== "" ? <span className="collapsible-count">{count}</span> : null}
        <span className="collapsible-chevron" aria-hidden="true" />
      </summary>
      <div id={panelId} className="collapsible-body">
        {children}
      </div>
    </details>
  );
}
