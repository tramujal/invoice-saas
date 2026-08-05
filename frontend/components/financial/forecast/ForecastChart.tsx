"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatPeriodLabel } from "@/lib/chart-format";

export type ForecastChartPoint = {
  period: string;
  /** Real historical value -- null for every future (forecast-only) point. */
  actual: number | null;
  /** Forecasted value -- null for every historical (actual-only) point,
   * EXCEPT the single boundary month, which the caller duplicates from
   * `actual` so the two line segments visually connect rather than
   * leaving a gap. */
  forecast: number | null;
  lower: number | null;
  upper: number | null;
};

type ForecastChartProps = {
  data: ForecastChartPoint[];
  formatValue: (value: number) => string;
  actualLabel: string;
  forecastLabel: string;
};

/** The one "historical vs. forecast, with a confidence band" chart every
 * forecast section uses. The band is drawn with recharts' standard
 * stacked-area trick: a transparent Area up to `lower`, then a second,
 * visible Area for exactly `upper - lower` stacked on top of it -- the
 * combined visual is a shaded region between lower and upper, without
 * recharts needing a native "range area" primitive. */
export function ForecastChart({ data, formatValue, actualLabel, forecastLabel }: ForecastChartProps) {
  const chartData = data.map((point) => ({
    period: formatPeriodLabel(point.period, "monthly"),
    actual: point.actual,
    forecast: point.forecast,
    lower: point.lower,
    bandWidth: point.lower !== null && point.upper !== null ? point.upper - point.lower : null,
  }));

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="period"
            tick={{ fontSize: 12, fill: "#64748b" }}
            axisLine={{ stroke: "#e2e8f0" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 12, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
            width={48}
            tickFormatter={(value: number) => formatValue(value)}
          />
          <Tooltip
            formatter={(value, name) => [value === null ? "—" : formatValue(Number(value)), name]}
            contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }}
          />
          <Area
            type="monotone"
            dataKey="lower"
            stackId="band"
            stroke="none"
            fill="transparent"
            legendType="none"
            isAnimationActive={false}
            tooltipType="none"
          />
          <Area
            type="monotone"
            dataKey="bandWidth"
            stackId="band"
            stroke="none"
            fill="#0f172a"
            fillOpacity={0.08}
            legendType="none"
            isAnimationActive={false}
            tooltipType="none"
          />
          <Line
            type="monotone"
            dataKey="actual"
            name={actualLabel}
            stroke="#0f172a"
            strokeWidth={2}
            dot={{ r: 3, fill: "#0f172a" }}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="forecast"
            name={forecastLabel}
            stroke="#0f172a"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={{ r: 3, fill: "#ffffff", stroke: "#0f172a" }}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
