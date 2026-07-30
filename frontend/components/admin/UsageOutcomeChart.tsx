"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformUsageMetrics } from "@/lib/types";

type UsageOutcomeChartProps = {
  data: PlatformUsageMetrics | null;
  loading?: boolean;
};

export function UsageOutcomeChart({ data, loading = false }: UsageOutcomeChartProps) {
  const { t } = useTranslation();

  const chartData = data
    ? [
        {
          name: t("opsDashboard.usageBackgroundJobs"),
          succeeded: data.background_jobs_succeeded_30d,
          failed: data.background_jobs_failed_30d,
        },
        {
          name: t("opsDashboard.usageWebhookDeliveries"),
          succeeded: data.webhook_deliveries_succeeded_30d,
          failed: data.webhook_deliveries_failed_30d,
        },
      ]
    : [];
  const hasData = chartData.some((row) => row.succeeded + row.failed > 0);

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("opsDashboard.usageOutcomeChartTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : !hasData ? (
        <p className="mt-5 text-sm text-slate-500">{t("opsDashboard.usageOutcomeChartEmpty")}</p>
      ) : (
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#64748b" }} axisLine={{ stroke: "#e2e8f0" }} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: "#64748b" }} axisLine={false} tickLine={false} width={32} allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="succeeded" name={t("opsDashboard.usageSucceeded")} fill="#0f766e" radius={[4, 4, 0, 0]} maxBarSize={40} />
              <Bar dataKey="failed" name={t("opsDashboard.usageFailed")} fill="#b91c1c" radius={[4, 4, 0, 0]} maxBarSize={40} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
