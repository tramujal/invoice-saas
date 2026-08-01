/** Phase UX4 -- shared "2h ago" / "3d ago" formatting for anywhere a
 * timestamp is shown as a glance-able recency cue rather than an exact
 * date (currently: the Notification Center). Deliberately falls back to
 * a locale-formatted absolute date/time past a week old, rather than
 * ever printing "3 weeks ago" -- relative phrasing stops being useful
 * (and starts requiring mental math) well before that, which is why
 * every major SaaS notification feed (GitHub, Linear, Slack) makes the
 * same switch. Pure function of (value, now, locale) -- `now` is an
 * explicit parameter (never `Date.now()` read internally) so this stays
 * trivially testable and never a source of snapshot-test flakiness. */

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;

export function formatRelativeTime(
  value: string | Date,
  now: Date = new Date(),
  locale?: string
): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const diffMs = now.getTime() - date.getTime();

  // Clock skew / a timestamp that's technically in the future by a few
  // seconds (client clock slightly behind the server that issued it) --
  // never show a negative "-3s ago"; treat anything under a minute as
  // "just now" in either direction.
  if (diffMs < MINUTE_MS) return "just now";

  if (diffMs < HOUR_MS) {
    const minutes = Math.floor(diffMs / MINUTE_MS);
    return `${minutes}m ago`;
  }
  if (diffMs < DAY_MS) {
    const hours = Math.floor(diffMs / HOUR_MS);
    return `${hours}h ago`;
  }
  if (diffMs < WEEK_MS) {
    const days = Math.floor(diffMs / DAY_MS);
    return `${days}d ago`;
  }

  return date.toLocaleDateString(locale, { month: "short", day: "numeric" });
}
