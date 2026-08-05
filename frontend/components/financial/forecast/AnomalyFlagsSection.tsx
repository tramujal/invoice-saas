"use client";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { AnomaliesResponse, ForecastAnomalySeverity } from "@/lib/types";

const SEVERITY_BADGE_CLASS: Record<ForecastAnomalySeverity, string> = {
  low: "bg-slate-100 text-slate-700 ring-slate-200/80",
  medium: "bg-amber-100 text-amber-900 ring-amber-200/80",
  high: "bg-red-100 text-red-900 ring-red-200/80",
};

type Props = {
  data: AnomaliesResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

/** Section: Anomaly Flags -- transparent, deterministic rules (revenue
 * drop, collection slowdown, overdue spike, large invoice, customer
 * concentration), each naming exactly which rule fired and the evidence
 * behind it (see app.financial_intelligence.forecasting.AnomalyFlag) --
 * never an opaque "something looks off." `evidence` is rendered directly
 * since it's a factual data readout, not narrative copy (same precedent
 * as Phase 24.1's AtRiskCustomer.evidence). */
export function AnomalyFlagsSection({ data, loading, planRestricted }: Props) {
  const { t } = useTranslation();
  if (planRestricted) return null;

  return (
    <section aria-label={t("financial.forecast.anomaliesHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("financial.forecast.anomaliesHeading")}
      </h2>

      {loading ? (
        <Skeleton className="h-24 w-full" />
      ) : !data || data.flags.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.anomaliesEmptyTitle")}
          description={t("financial.forecast.anomaliesEmptyDescription")}
        />
      ) : (
        <div className="space-y-2">
          {data.flags.map((flag, index) => (
            <div
              key={index}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
            >
              <div>
                <p className="text-sm font-medium text-slate-800">
                  {t(`financial.forecast.anomalyRule.${flag.rule}`)}
                  {flag.currency_code ? ` (${flag.currency_code})` : ""}
                </p>
                <p className="text-xs text-slate-500">{flag.evidence}</p>
              </div>
              <Badge className={SEVERITY_BADGE_CLASS[flag.severity]}>
                {t(`financial.forecast.severity.${flag.severity}`)}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
