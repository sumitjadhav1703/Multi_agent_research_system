import { useEffect, useState } from "react";

/**
 * First visit in this tab session → expand secondary panels.
 * Leaving and returning (key already set) → start collapsed.
 */
export function useFirstVisitExpand(pageKey: string): boolean {
  const storageKey = `researchmind.panels.${pageKey}`;
  const [expandByDefault] = useState(() => {
    try {
      return sessionStorage.getItem(storageKey) !== "1";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, "1");
    } catch {
      /* ignore quota / private mode */
    }
  }, [storageKey]);

  return expandByDefault;
}
