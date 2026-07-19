// Render backend timestamps in the viewer's local timezone and locale.
//
// The backend sends UTC ISO 8601 strings (e.g. "2026-07-18T18:00:38+00:00").
// Older rows may still hold a naive "YYYY-MM-DD HH:MM:SS" string, which the
// Date constructor interprets as local time — a reasonable fallback.

function parse(value: string | null | undefined): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Local date + time, e.g. "18 Jul 2026, 20:00". */
export function formatDateTime(value: string | null | undefined): string {
  const date = parse(value)
  if (!date) return value ?? "—"
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
}

/** Local date only, e.g. "18 Jul 2026". */
export function formatDate(value: string | null | undefined): string {
  const date = parse(value)
  if (!date) return value ?? "—"
  return date.toLocaleDateString(undefined, { dateStyle: "medium" })
}

/**
 * A video's publish date. Approximate dates (from the cheap channel listing)
 * are day-level only, so they are shown as a date with a "~" marker; exact
 * dates include the local time.
 */
export function formatPublished(
  value: string | null | undefined,
  approximate = false,
): string {
  if (!value) return "—"
  return approximate ? `~${formatDate(value)}` : formatDateTime(value)
}
