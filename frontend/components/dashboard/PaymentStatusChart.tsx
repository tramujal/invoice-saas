"use client";

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  PAYMENT_STATUS_CHART_COLOR,
  getPaymentStatusLabel,
} from "@/lib/payment-status";
import type { PaymentStatusCountPoint } from "@/lib/types";

type PaymentStatusChartProps = {
  data: PaymentStatusCountPoint[];
  loading?: boolean;
};

export function PaymentStatusChart({
  data,
  loading = false,
}: PaymentStatusChartProps) {
  const { t } = useTranslation();
  const total = data.reduce((sum, point) => sum + point.count, 0);

  const chartData = data
    .filter((point) => point.count > 0)
    .map((point) => ({
      name: getPaymentStatusLabel(t, point.status),
      value: point.count,
      color: PAYMENT_STATUS_CHART_COLOR[point.status],
    }));

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("dashboard.paymentStatusChartTitle")}
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : total === 0 ? (
        <p className="mt-5 text-sm text-slate-500">
          {t("dashboard.chartEmptyNoInvoices")}
        </p>
      ) : (
        <div className="mt-2 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={2}
              >
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }} />
              <Legend
                verticalAlign="bottom"
                height={28}
                wrapperStyle={{ fontSize: 12, color: "#475569" }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
