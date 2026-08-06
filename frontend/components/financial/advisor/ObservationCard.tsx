"use client";

import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Observation } from "@/lib/types";

import { SeverityBadge } from "./AdvisorBadges";

/** One AI-authored observation -- every field here is content the model
 * itself generated (unlike FinancialMetricValue.label/note elsewhere in
 * this app), so it's rendered directly, not re-translated by the
 * frontend. `evidence` is the model's own citation of the exact
 * deterministic metric(s) backing this observation -- see
 * app.financial_intelligence.schemas_ai.Observation, which requires at
 * least one evidence item for every observation to even exist. */
export function ObservationCard({ observation }: { observation: Observation }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            {t(`financial.advisor.category.${observation.category}`)}
          </span>
          <h4 className="mt-0.5 text-sm font-semibold text-slate-900">{observation.title}</h4>
        </div>
        <SeverityBadge severity={observation.severity} />
      </div>
      <p className="mt-2 text-sm text-slate-600">{observation.explanation}</p>
      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        {observation.evidence.map((item, i) => (
          <div key={i} className="flex items-baseline gap-1 text-xs">
            <dt className="text-slate-400">{item.label}:</dt>
            <dd className="font-medium text-slate-700">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
