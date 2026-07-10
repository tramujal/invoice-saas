"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatMonthLabel } from "@/lib/chart-format";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { MonthlySummaryPoint } from "@/lib/types";

type InvoiceVolumeChartProps = {
  data: MonthlySummaryPoint[];
  loading?: boolean;
};

export function InvoiceVolumeChart({ data, loading = false }: InvoiceVolumeChartProps) {
  const { t } = useTranslation();
  const hasData = data.some((point) => point.invoice_count > 0);

  const chartData = data.map((point) => ({
    month: formatMonthLabel(point.month),
    invoices: point.invoice_count,
  }));

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("dashboard.invoiceVolumeTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : !hasData ? (
        <p className="mt-5 text-sm text-slate-500">
          {t("dashboard.chartEmptyNoInvoices")}
        </p>
      ) : (
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={{ stroke: "#e2e8f0" }}
                tickLine={false}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 12, fill: "#64748b" }}
                axisLine={false}
                tickLine={false}
                width={32}
              />
              <Tooltip contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }} />
              <Bar
                dataKey="invoices"
                name={t("nav.invoices")}
                fill="#334155"
                radius={[4, 4, 0, 0]}
                maxBarSize={32}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
