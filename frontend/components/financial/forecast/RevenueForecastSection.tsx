"use client";

import { useMemo } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { MonthlyProjectionResponse, RevenueForecastResponse, RevenueTrendsResponse } from "@/lib/types";

import { ForecastChart, type ForecastChartPoint } from "./ForecastChart";
import { ForecastConfidenceBadge } from "./ForecastConfidenceBadge";

type RevenueForecastSectionProps = {
  forecast: RevenueForecastResponse | null;
  monthlyProjection: MonthlyProjectionResponse | null;
  trends: RevenueTrendsResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

const HORIZON_ORDER = [30, 90, 180, 365];

function buildChartSeries(
  currencyCode: string,
  trends: RevenueTrendsResponse | null,
  monthlyProjection: MonthlyProjectionResponse | null
): ForecastChartPoint[] {
  const byPeriod = new Map<string, ForecastChartPoint>();

  for (const point of trends?.points ?? []) {
    if (point.currency_code !== currencyCode) continue;
    byPeriod.set(point.period, {
      period: point.period,
      actual: Number.parseFloat(point.invoiced),
      forecast: null,
      lower: null,
      upper: null,
    });
  }
  for (const point of monthlyProjection?.points ?? []) {
    if (point.currency_code !== currencyCode) continue;
    byPeriod.set(point.month, {
      period: point.month,
      actual: null,
      forecast: Number.parseFloat(point.expected_value),
      lower: Number.parseFloat(point.lower_bound),
      upper: Number.parseFloat(point.upper_bound),
    });
  }

  const series = Array.from(byPeriod.values()).sort((a, b) => a.period.localeCompare(b.period));

  // Bridge the gap between the last real month and the first forecasted
  // one: duplicate the last actual value as that same point's forecast,
  // so the solid and dashed line segments visually connect instead of
  // leaving a break in the chart.
  const lastActualIndex = series.slice().reverse().findIndex((p) => p.actual !== null);
  if (lastActualIndex !== -1) {
    const index = series.length - 1 - lastActualIndex;
    const nextIndex = index + 1;
    if (nextIndex < series.length && series[nextIndex].forecast !== null) {
      series[index] = { ...series[index], forecast: series[index].actual };
    }
  }

  return series;
}

/** Section: Revenue Forecast -- a historical-vs-forecast chart with a
 * confidence band, plus 30/90/180/365-day horizon cards, one full block
 * per currency (see docs/financial_dashboard.md's currency-separation
 * convention, unchanged by this phase). The 365-day horizon is simply
 * absent from `forecast.horizons` (never a fabricated 0) whenever there
 * isn't enough real history to justify it -- see
 * app.financial_intelligence.forecasting.MIN_HISTORY_FOR_365D_HORIZON. */
export function RevenueForecastSection({
  forecast,
  monthlyProjection,
  trends,
  loading,
  planRestricted,
}: RevenueForecastSectionProps) {
  const { t } = useTranslation();

  const chartSeriesByCurrency = useMemo(() => {
    const codes = new Set<string>();
    for (const p of trends?.points ?? []) codes.add(p.currency_code);
    for (const p of monthlyProjection?.points ?? []) codes.add(p.currency_code);
    const map: Record<string, ForecastChartPoint[]> = {};
    for (const code of Array.from(codes)) {
      map[code] = buildChartSeries(code, trends, monthlyProjection);
    }
    return map;
  }, [trends, monthlyProjection]);

  if (planRestricted) {
    return (
      <section aria-label={t("financial.forecast.revenueHeading")} className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("financial.forecast.revenueHeading")}
        </h2>
        <EmptyState
          title={t("financial.forecast.planRestrictedTitle")}
          description={t("financial.forecast.planRestrictedDescription")}
        />
      </section>
    );
  }

  return (
    <section aria-label={t("financial.forecast.revenueHeading")} className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("financial.forecast.revenueHeading")}
        </h2>
        <p className="mt-1 text-sm text-slate-500">{t("financial.forecast.revenueSubtitle")}</p>
      </div>

      {loading ? (
        <Skeleton className="h-64 w-full" />
      ) : !forecast || forecast.results.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.insufficientDataTitle")}
          description={t("financial.forecast.insufficientDataDescription")}
        />
      ) : (
        forecast.results.map((result) => (
          <div
            key={result.currency_code}
            className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-600">{result.currency_code}</h3>
              <div className="flex items-center gap-2">
                {result.model ? (
                  <span className="text-xs text-slate-500">
                    {t(`financial.forecast.method.${result.model}`)}
                  </span>
                ) : null}
                <ForecastConfidenceBadge confidence={result.confidence} />
              </div>
            </div>

            {result.status === "insufficient_data" ? (
              <EmptyState
                title={t("financial.forecast.insufficientDataTitle")}
                description={t("financial.forecast.insufficientDataMinimum", {
                  needed: String(result.minimum_observations_required),
                  have: String(result.sample_size),
                })}
              />
            ) : (
              <>
                <ForecastChart
                  data={chartSeriesByCurrency[result.currency_code] ?? []}
                  formatValue={(v) => formatMoney(v)}
                  actualLabel={t("financial.forecast.chartActual")}
                  forecastLabel={t("financial.forecast.chartForecast")}
                />
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {HORIZON_ORDER.map((days) => {
                    const horizon = result.horizons.find((h) => h.horizon_days === days);
                    if (!horizon) return null;
                    return (
                      <div key={days} className="rounded-xl border border-slate-200 px-3 py-2.5">
                        <dt className="text-xs font-medium text-slate-500">
                          {t(`financial.forecast.horizon.${days}`)}
                        </dt>
                        <dd className="mt-1 text-sm font-semibold text-slate-900">
                          {result.currency_code} {formatMoney(Number(horizon.forecast_value))}
                        </dd>
                        <dd className="text-xs text-slate-500">
                          {formatMoney(Number(horizon.lower_bound))} – {formatMoney(Number(horizon.upper_bound))}
                        </dd>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        ))
      )}
    </section>
  );
}
