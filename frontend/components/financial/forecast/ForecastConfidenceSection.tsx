"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { ForecastSummaryResponse } from "@/lib/types";

import { ForecastConfidenceBadge } from "./ForecastConfidenceBadge";

type Props = {
  data: ForecastSummaryResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

/** Section: Forecast Confidence -- a compact, per-currency strip (model
 * selected, confidence tier, any open anomaly count) that sits above the
 * detailed sections below it, so a reader gets the "how much should I
 * trust this" signal before the numbers themselves. */
export function ForecastConfidenceSection({ data, loading, planRestricted }: Props) {
  const { t } = useTranslation();

  if (planRestricted) {
    return (
      <section aria-label={t("financial.forecast.confidenceHeading")} className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("financial.forecast.confidenceHeading")}
        </h2>
        <EmptyState
          title={t("financial.forecast.planRestrictedTitle")}
          description={t("financial.forecast.planRestrictedDescription")}
        />
      </section>
    );
  }

  return (
    <section aria-label={t("financial.forecast.confidenceHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("financial.forecast.confidenceHeading")}
      </h2>

      {loading ? (
        <Skeleton className="h-16 w-full" />
      ) : !data || data.results.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.insufficientDataTitle")}
          description={t("financial.forecast.insufficientDataDescription")}
        />
      ) : (
        <div className="flex flex-wrap gap-3">
          {data.results.map((result) => (
            <div
              key={result.currency_code}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
            >
              <span className="text-sm font-semibold text-slate-700">{result.currency_code}</span>
              {result.model ? (
                <span className="text-xs text-slate-500">{t(`financial.forecast.method.${result.model}`)}</span>
              ) : null}
              <ForecastConfidenceBadge confidence={result.confidence} />
              {result.anomaly_count > 0 ? (
                <span className="text-xs font-medium text-amber-700">
                  {t("financial.forecast.anomalyCount", { count: String(result.anomaly_count) })}
                </span>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
