"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatDayLabel } from "@/lib/chart-format";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformDailySignupCount } from "@/lib/types";

type DailySignupsChartProps = {
  data: PlatformDailySignupCount[];
  loading?: boolean;
};

export function DailySignupsChart({ data, loading = false }: DailySignupsChartProps) {
  const { t } = useTranslation();
  const chartData = data.map((point) => ({ day: formatDayLabel(point.day), count: point.count }));
  const hasData = chartData.length > 0;

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("opsDashboard.dailySignupsChartTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : !hasData ? (
        <p className="mt-5 text-sm text-slate-500">{t("opsDashboard.dailySignupsChartEmpty")}</p>
      ) : (
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 12, fill: "#64748b" }} axisLine={{ stroke: "#e2e8f0" }} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: "#64748b" }} axisLine={false} tickLine={false} width={32} allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }} />
              <Bar dataKey="count" name={t("opsDashboard.dailySignupsLabel")} fill="#0f172a" radius={[4, 4, 0, 0]} maxBarSize={32} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
