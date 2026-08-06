"use client";

import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Recommendation } from "@/lib/types";

import { PriorityBadge } from "./AdvisorBadges";

/** One AI-authored recommendation -- `reason` names the real metric(s)
 * behind it and `limitations` acknowledges its own uncertainty, both
 * required fields (see app.financial_intelligence.schemas_ai
 * .Recommendation) so a recommendation can never appear as a bare
 * imperative with nothing backing it. */
export function RecommendationCard({ recommendation }: { recommendation: Recommendation }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="text-sm font-semibold text-slate-900">{recommendation.title}</h4>
        <PriorityBadge priority={recommendation.priority} />
      </div>
      <p className="mt-2 text-sm text-slate-700">{recommendation.action}</p>
      <p className="mt-2 text-xs text-slate-500">
        <span className="font-medium text-slate-600">{t("financial.advisor.reasonLabel")}: </span>
        {recommendation.reason}
      </p>
      <p className="mt-1 text-xs text-slate-500">
        <span className="font-medium text-slate-600">{t("financial.advisor.expectedImpactLabel")}: </span>
        {recommendation.expected_impact}
      </p>
      <p className="mt-1 text-xs text-slate-400">
        <span className="font-medium text-slate-500">{t("financial.advisor.limitationsLabel")}: </span>
        {recommendation.limitations}
      </p>
    </div>
  );
}
