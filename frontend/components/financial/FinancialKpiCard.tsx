"use client";

import { Skeleton } from "@/components/ui/Skeleton";
import { TrendIndicator } from "@/components/analytics/TrendIndicator";
import { useAnimatedNumber } from "@/lib/use-animated-number";
import { formatMoney } from "@/lib/money";
import type { FinancialMetricValue, TrendDirection } from "@/lib/types";

export type FinancialKpiFormat = "currency" | "percent" | "days" | "number";

function formatValue(value: number, format: FinancialKpiFormat, currencyCode: string | null): string {
  if (format === "currency") return `${currencyCode ?? ""} ${formatMoney(value)}`.trim();
  if (format === "percent") return `${value.toFixed(2)}%`;
  if (format === "days") return value.toFixed(1);
  return formatMoney(value);
}

type FinancialKpiCardProps = {
  metric: FinancialMetricValue;
  format: FinancialKpiFormat;
  /** A translated title, supplied by the caller -- metric.label itself
   * is a plain English string the backend uses for its own logs/API
   * consumers (see MetricValue's own docstring), never localized, so it
   * must never be rendered directly as user-facing copy. Same reasoning
   * as the existing analytics page's average_payment_time.reason: "an
   * internal-facing string by design, not end-user copy." */
  label: string;
  /** A short, translated explanation of how this figure is calculated --
   * shown as a native tooltip on the info affordance, per the phase's own
   * "tooltip explaining calculation" requirement. */
  tooltip: string;
  /** Shown in place of a trend badge whenever no previous-period
   * comparison exists for this metric (see MetricValue's own docstring:
   * previous_value/percent_change/trend_direction are null together
   * exactly then) -- translated by the caller, which knows specifically
   * *why* (a point-in-time balance, a forward-looking projection, too
   * little monthly sample size, ...), never the backend's own raw note. */
  noComparisonCaption?: string;
  loading?: boolean;
};

/** One Executive KPI card: current value (animated), an optional
 * previous-period comparison (trend arrow + percentage), and a tooltip
 * explaining the formula. */
export function FinancialKpiCard({
  metric,
  format,
  label,
  tooltip,
  noComparisonCaption,
  loading = false,
}: FinancialKpiCardProps) {
  const numericValue = metric.value === null ? null : Number.parseFloat(metric.value);
  const animated = useAnimatedNumber(numericValue);
  const hasComparison = metric.trend_direction !== null && metric.percent_change !== null;

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition duration-150 hover:shadow-md sm:p-6">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</h3>
        <span
          className="mt-0.5 flex h-4 w-4 shrink-0 cursor-help items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-500"
          title={tooltip}
          aria-label={tooltip}
        >
          i
        </span>
      </div>

      {loading ? (
        <div className="mt-3 space-y-2">
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-4 w-20" />
        </div>
      ) : (
        <>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
            {numericValue === null
              ? "—"
              : formatValue(animated ?? numericValue, format, metric.currency_code)}
          </p>
          <div className="mt-2 min-h-[22px]">
            {hasComparison ? (
              <TrendIndicator
                direction={metric.trend_direction as TrendDirection}
                percentageDifference={metric.percent_change}
              />
            ) : noComparisonCaption ? (
              <p className="text-xs text-slate-400">{noComparisonCaption}</p>
            ) : null}
          </div>
        </>
      )}
    </article>
  );
}
