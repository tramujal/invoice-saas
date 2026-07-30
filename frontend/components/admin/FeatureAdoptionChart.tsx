"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipValueType } from "recharts";

import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformFeatureAdoption } from "@/lib/types";

type FeatureAdoptionChartProps = {
  data: PlatformFeatureAdoption[];
  loading?: boolean;
};

const FEATURE_LABEL_KEYS: Record<string, string> = {
  analytics_enabled: "opsDashboard.featureAnalytics",
  forecasting_enabled: "opsDashboard.featureForecasting",
  ai_enabled: "opsDashboard.featureAi",
  background_jobs_enabled: "opsDashboard.featureBackgroundJobs",
  custom_branding_enabled: "opsDashboard.featureCustomBranding",
  api_access_enabled: "opsDashboard.featureApiAccess",
  advanced_reports_enabled: "opsDashboard.featureAdvancedReports",
};

export function FeatureAdoptionChart({ data, loading = false }: FeatureAdoptionChartProps) {
  const { t } = useTranslation();
  const chartData = data.map((row) => ({
    name: t(FEATURE_LABEL_KEYS[row.feature] ?? row.feature),
    percent: row.adopted_percent,
  }));
  const hasData = chartData.some((row) => row.percent > 0);

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("opsDashboard.featureAdoptionChartTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-64 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : !hasData ? (
        <p className="mt-5 text-sm text-slate-500">{t("opsDashboard.featureAdoptionChartEmpty")}</p>
      ) : (
        <div className="mt-4 h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical" margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis
                type="number"
                domain={[0, 100]}
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={{ stroke: "#e2e8f0" }}
                tickLine={false}
                tickFormatter={(value: number) => `${value}%`}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={false}
                tickLine={false}
                width={120}
              />
              <Tooltip
                formatter={(value: TooltipValueType | undefined) => `${value}%`}
                contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }}
              />
              <Bar dataKey="percent" name={t("opsDashboard.featureAdoptionValueLabel")} fill="#475569" radius={[0, 4, 4, 0]} maxBarSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
