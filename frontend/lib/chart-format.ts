/** Formats a "YYYY-MM" key (from the dashboard analytics endpoint) as a
 * short human label, e.g. "2026-02" -> "Feb 2026". Shared by every chart
 * that plots the monthly_summary series. */
export function formatMonthLabel(monthKey: string): string {
  const [year, month] = monthKey.split("-").map(Number);
  if (!year || !month) return monthKey;
  const date = new Date(year, month - 1, 1);
  return date.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}
