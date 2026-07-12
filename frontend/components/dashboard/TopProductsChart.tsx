"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipValueType,
} from "recharts";

import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { TopProductRevenue } from "@/lib/types";

type TopProductsChartProps = {
  /** The full top_products_and_services list -- this component filters to
   * type === "product" internally, mirroring how TopServicesChart filters
   * the same list to "service" (one flat, currency-tagged, type-tagged
   * list is ranked independently per (currency, type) server-side; see
   * app.product_analytics). */
  data: TopProductRevenue[];
  loading?: boolean;
};

export function TopProductsChart({ data, loading = false }: TopProductsChartProps) {
  const { t } = useTranslation();
  const chartData = data
    .filter((row) => row.product_type === "product")
    .map((row) => ({
      name: row.product_name,
      revenue: Number.parseFloat(row.revenue),
    }));

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("dashboard.topProductsTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : chartData.length === 0 ? (
        <p className="mt-5 text-sm text-slate-500">{t("dashboard.topProductsEmpty")}</p>
      ) : (
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis
                type="number"
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={{ stroke: "#e2e8f0" }}
                tickLine={false}
                tickFormatter={(value: number) => formatMoney(value)}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={false}
                tickLine={false}
                width={100}
              />
              <Tooltip
                formatter={(value: TooltipValueType | undefined) => formatMoney(Number(value))}
                contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }}
              />
              <Bar
                dataKey="revenue"
                name={t("dashboard.revenueLabel")}
                fill="#0284c7"
                radius={[0, 4, 4, 0]}
                maxBarSize={24}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
