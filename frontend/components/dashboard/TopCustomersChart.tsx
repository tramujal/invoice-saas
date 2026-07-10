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

import { formatMoney } from "@/lib/money";
import type { TopCustomerRevenue } from "@/lib/types";

type TopCustomersChartProps = {
  data: TopCustomerRevenue[];
  loading?: boolean;
};

export function TopCustomersChart({ data, loading = false }: TopCustomersChartProps) {
  const chartData = data.map((row) => ({
    name: row.customer_name,
    revenue: Number.parseFloat(row.revenue),
  }));

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Top customers by revenue
      </h2>

      {loading ? (
        <div className="mt-5 h-56 w-full animate-pulse rounded-lg bg-slate-100" />
      ) : chartData.length === 0 ? (
        <p className="mt-5 text-sm text-slate-500">
          No customer revenue yet. Attach a customer to an invoice to see them here.
        </p>
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
              <Bar dataKey="revenue" fill="#0f172a" radius={[0, 4, 4, 0]} maxBarSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}
