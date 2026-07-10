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

import { formatMonthLabel } from "@/lib/chart-format";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { MonthlySummaryPoint } from "@/lib/types";

type RevenueTrendLineChartProps = {
  data: MonthlySummaryPoint[];
  loading?: boolean;
};

export function RevenueTrendLineChart({
  data,
  loading = false,
}: RevenueTrendLineChartProps) {
  const { t } = useTranslation();
  const hasData = data.some((point) => Number.parseFloat(point.revenue) > 0);

  const chartData = data.map((point) => ({
    month: formatMonthLabel(point.month),
    revenue: Number.parseFloat(point.revenue),
  }));

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("dashboard.revenueTrendChartTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : !hasData ? (
        <p className="mt-5 text-sm text-slate-500">
          {t("dashboard.chartEmptyNoRevenue")}
        </p>
      ) : (
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={{ stroke: "#e2e8f0" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={false}
                tickLine={false}
                width={48}
                tickFormatter={(value: number) => formatMoney(value)}
              />
              <Tooltip
                formatter={(value: TooltipValueType | undefined) => formatMoney(Number(value))}
                contentStyle={{
                  borderRadius: 8,
                  borderColor: "#e2e8f0",
                  fontSize: 12,
                }}
              />
              <Line
                type="monotone"
                dataKey="revenue"
                name={t("dashboard.revenueLabel")}
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
