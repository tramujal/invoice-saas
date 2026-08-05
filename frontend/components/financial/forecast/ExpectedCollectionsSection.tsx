"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { CollectionsForecastResponse } from "@/lib/types";

import { ForecastConfidenceBadge } from "./ForecastConfidenceBadge";

const HORIZON_ORDER = [30, 90, 180];

type Props = {
  data: CollectionsForecastResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

/** Section: Expected Collections -- known (from currently-open invoices,
 * customer-aware payment-delay projection, falling back to the
 * organization-wide average) plus projected (forecasted future revenue x
 * this organization's own historical collection rate) amounts for each of
 * the 30/90/180-day horizons, stacked bars per horizon so the two
 * components stay visually distinct rather than one opaque total. */
export function ExpectedCollectionsSection({ data, loading, planRestricted }: Props) {
  const { t } = useTranslation();

  if (planRestricted) {
    return (
      <section aria-label={t("financial.forecast.collectionsHeading")} className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("financial.forecast.collectionsHeading")}
        </h2>
        <EmptyState
          title={t("financial.forecast.planRestrictedTitle")}
          description={t("financial.forecast.planRestrictedDescription")}
        />
      </section>
    );
  }

  return (
    <section aria-label={t("financial.forecast.collectionsHeading")} className="space-y-6">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("financial.forecast.collectionsHeading")}
      </h2>

      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : !data || data.results.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.collectionsEmptyTitle")}
          description={t("financial.forecast.collectionsEmptyDescription")}
        />
      ) : (
        data.results.map((result) => {
          const chartData = HORIZON_ORDER.map((days) => {
            const h = result.horizons.find((horizon) => horizon.horizon_days === days);
            return {
              horizon: t(`financial.forecast.horizon.${days}`),
              known: h ? Number.parseFloat(h.known_amount) : 0,
              projected: h ? Number.parseFloat(h.projected_amount) : 0,
            };
          });

          return (
            <div
              key={result.currency_code}
              className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-slate-600">{result.currency_code}</h3>
                <ForecastConfidenceBadge confidence={result.confidence} />
              </div>

              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="horizon" tick={{ fontSize: 12, fill: "#64748b" }} axisLine={{ stroke: "#e2e8f0" }} tickLine={false} />
                    <YAxis
                      tick={{ fontSize: 12, fill: "#64748b" }}
                      axisLine={false}
                      tickLine={false}
                      width={48}
                      tickFormatter={(v: number) => formatMoney(v)}
                    />
                    <Tooltip formatter={(value) => formatMoney(Number(value))} contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }} />
                    <Bar dataKey="known" name={t("financial.forecast.known")} stackId="collections" fill="#0f172a" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="projected" name={t("financial.forecast.projected")} stackId="collections" fill="#94a3b8" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {HORIZON_ORDER.map((days) => {
                  const horizon = result.horizons.find((h) => h.horizon_days === days);
                  if (!horizon) return null;
                  return (
                    <div key={days} className="rounded-xl border border-slate-200 px-3 py-2.5">
                      <dt className="text-xs font-medium text-slate-500">{t(`financial.forecast.horizon.${days}`)}</dt>
                      <dd className="mt-1 text-sm font-semibold text-slate-900">
                        {result.currency_code} {formatMoney(Number(horizon.total_expected))}
                      </dd>
                      <dd className="text-xs text-slate-500">
                        {t("financial.forecast.knownVsProjected", {
                          known: formatMoney(Number(horizon.known_amount)),
                          projected: formatMoney(Number(horizon.projected_amount)),
                        })}
                      </dd>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
      )}
    </section>
  );
}
