/** Formatting helpers. Hebrew locale, Israeli date order. */

const DATE = new Intl.DateTimeFormat("he-IL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const DATE_TIME = new Intl.DateTimeFormat("he-IL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : DATE.format(d);
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : DATE_TIME.format(d);
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Confidence as a whole percentage. 0.87 -> "87%" */
export function formatConfidence(value: number | null): string {
  if (value === null) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Below this the backend flags a value as low confidence; the bar is coloured
 *  to match so the two never disagree on screen. */
export const LOW_CONFIDENCE = 0.75;
