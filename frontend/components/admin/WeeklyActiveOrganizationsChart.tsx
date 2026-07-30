"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatDayLabel } from "@/lib/chart-format";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformWeeklyActiveOrganizationsCount } from "@/lib/types";

type WeeklyActiveOrganizationsChartProps = {
  data: PlatformWeeklyActiveOrganizationsCount[];
  loading?: boolean;
};

export function WeeklyActiveOrganizationsChart({ data, loading = false }: WeeklyActiveOrganizationsChartProps) {
  const { t } = useTranslation();
  const chartData = data.map((point) => ({ week: formatDayLabel(point.week_start), count: point.count }));
  const hasData = chartData.length > 0;

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("opsDashboard.weeklyActiveChartTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : !hasData ? (
        <p className="mt-5 text-sm text-slate-500">{t("opsDashboard.weeklyActiveChartEmpty")}</p>
      ) : (
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="week" tick={{ fontSize: 12, fill: "#64748b" }} axisLine={{ stroke: "#e2e8f0" }} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: "#64748b" }} axisLine={false} tickLine={false} width={32} allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="count"
                name={t("opsDashboard.weeklyActiveLabel")}
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
