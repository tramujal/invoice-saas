"use client";

import { Badge } from "@/components/ui/Badge";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { ForecastConfidenceLevel } from "@/lib/types";

const CONFIDENCE_BADGE_CLASS: Record<ForecastConfidenceLevel, string> = {
  insufficient_data: "bg-slate-100 text-slate-600 ring-slate-200/80",
  low: "bg-amber-100 text-amber-900 ring-amber-200/80",
  medium: "bg-blue-100 text-blue-900 ring-blue-200/80",
  high: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
};

/** The one confidence badge every forecast card/table row uses -- see
 * app.financial_intelligence.confidence.ConfidenceLevel. Sample size gates
 * the ceiling; backtest error can only pull it down, never raise it
 * (matching that module's own docstring). */
export function ForecastConfidenceBadge({ confidence }: { confidence: ForecastConfidenceLevel }) {
  const { t } = useTranslation();
  return (
    <Badge className={CONFIDENCE_BADGE_CLASS[confidence]}>
      {t(`financial.forecast.confidence.${confidence}`)}
    </Badge>
  );
}
