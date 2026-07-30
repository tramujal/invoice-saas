/** Formats a "YYYY-MM" key (from the dashboard analytics endpoint) as a
 * short human label, e.g. "2026-02" -> "Feb 2026". Shared by every chart
 * that plots the monthly_summary series. */
export function formatMonthLabel(monthKey: string): string {
  const [year, month] = monthKey.split("-").map(Number);
  if (!year || !month) return monthKey;
  const date = new Date(year, month - 1, 1);
  return date.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

/** Formats a generic evolution-series period label (see
 * app.analytics.calculators.trends.SeriesPoint) for any of the 3
 * granularities: "2026-07" -> "Jul 2026" (delegates to formatMonthLabel),
 * "2026-Q3" -> "Q3 2026", "2026" -> "2026" unchanged. Used by
 * MonthlyEvolutionChart instead of a fixed month-only formatter, since
 * that chart is granularity-aware. */
export function formatPeriodLabel(period: string, granularity: "monthly" | "quarterly" | "yearly"): string {
  if (granularity === "monthly") return formatMonthLabel(period);
  if (granularity === "quarterly") {
    const [year, quarter] = period.split("-Q");
    return quarter ? `Q${quarter} ${year}` : period;
  }
  return period;
}

/** Formats an ISO "YYYY-MM-DD" date key as a short day label, e.g.
 * "2026-07-30" -> "Jul 30". Used by the Phase 21 operations dashboard's
 * daily/weekly growth charts. */
export function formatDayLabel(dateKey: string): string {
  const date = new Date(`${dateKey}T00:00:00`);
  if (Number.isNaN(date.getTime())) return dateKey;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
