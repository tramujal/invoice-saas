"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipValueType,
} from "recharts";

import { formatPeriodLabel } from "@/lib/chart-format";
import type { SeriesGranularity, SeriesPoint } from "@/lib/types";

type MonthlyEvolutionChartProps = {
  title: string;
  /** Pre-filtered by the caller to a single series (e.g. one currency's
   * revenue, or a currency-agnostic count) -- this component never
   * combines multiple series itself, the same convention
   * RevenueTrendLineChart already established. */
  data: SeriesPoint[];
  granularity: SeriesGranularity;
  emptyMessage: string;
  loading?: boolean;
  valueName: string;
  formatValue: (value: number) => string;
};

/** The one generic evolution-series chart every "how is X evolving over
 * time" section uses (revenue per currency, invoice count, customer
 * count, quote conversions) -- consumes SeriesPoint[] directly rather
 * than a chart-specific shape, per this phase's own "the frontend should
 * consume generic series" instruction. */
export function MonthlyEvolutionChart({
  title,
  data,
  granularity,
  emptyMessage,
  loading = false,
  valueName,
  formatValue,
}: MonthlyEvolutionChartProps) {
  const hasData = data.some((point) => Number.parseFloat(point.value) > 0);

  const chartData = data.map((point) => ({
    period: formatPeriodLabel(point.period, granularity),
    value: Number.parseFloat(point.value),
  }));

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : !hasData ? (
        <p className="mt-5 text-sm text-slate-500">{emptyMessage}</p>
      ) : (
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="period"
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={{ stroke: "#e2e8f0" }}
                tickLine={false}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={false}
                tickLine={false}
                width={48}
                tickFormatter={(value: number) => formatValue(value)}
              />
              <Tooltip
                formatter={(value: TooltipValueType | undefined) => formatValue(Number(value))}
                contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }}
              />
              <Line
                type="monotone"
                dataKey="value"
                name={valueName}
                stroke="#0f172a"
                strokeWidth={2}
                dot={{ r: 3, fill: "#0f172a" }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
