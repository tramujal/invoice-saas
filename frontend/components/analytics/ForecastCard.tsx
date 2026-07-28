"use client";

import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Forecast, ForecastMethod } from "@/lib/types";

const METHOD_LABEL_KEY: Record<ForecastMethod, string> = {
  simple_moving_average: "analytics.forecast.method.simpleMovingAverage",
  weighted_moving_average: "analytics.forecast.method.weightedMovingAverage",
  linear_trend: "analytics.forecast.method.linearTrend",
};

type ForecastCardProps = {
  title: string;
  forecast: Forecast;
  loading: boolean;
  formatValue: (value: string) => string;
};

/** Renders a single forecast -- available=false is an honest gap (fewer
 * than 2 historical periods), never a fabricated value (see
 * app.analytics.forecast's own docstring). The caption is built from
 * `method`/`window_size`/`inputs.length` (structured, always-translated
 * fields), never from the backend's own `reason` string, which is an
 * internal-facing message, not end-user copy -- the same rule this app
 * already applies to average_payment_time.reason. */
export function ForecastCard({ title, forecast, loading, formatValue }: ForecastCardProps) {
  const { t } = useTranslation();

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {loading ? (
        <div className="mt-3 space-y-2" aria-hidden>
          <div className="h-8 w-24 animate-pulse rounded-lg bg-slate-200" />
          <div className="h-4 w-40 animate-pulse rounded bg-slate-100" />
        </div>
      ) : !forecast.available || forecast.forecast_value === null || forecast.method === null ? (
        <p className="mt-3 text-sm text-slate-500">{t("analytics.forecast.unavailable")}</p>
      ) : (
        <>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
            {formatValue(forecast.forecast_value)}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            {t("analytics.forecast.caption", {
              method: t(METHOD_LABEL_KEY[forecast.method]),
              periods: forecast.window_size ?? forecast.inputs.length,
            })}
          </p>
        </>
      )}
    </article>
  );
}
