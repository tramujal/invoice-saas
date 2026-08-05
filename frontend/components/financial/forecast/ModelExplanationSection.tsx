"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { FORECAST_MODEL_NAMES } from "@/lib/types";
import type { ForecastAccuracyResponse, ForecastMethodsResponse } from "@/lib/types";

type Props = {
  methods: ForecastMethodsResponse | null;
  accuracy: ForecastAccuracyResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

/** Section: Model Explanation -- describes what each of the 4 candidate
 * models does (static, translated copy — never the backend's own
 * internal names rendered as prose) and highlights whichever one was
 * actually selected for at least one currency, per
 * app.financial_intelligence.backtesting.select_best_model. */
export function ModelExplanationSection({ methods, accuracy, loading, planRestricted }: Props) {
  const { t } = useTranslation();
  if (planRestricted) return null;

  const selectedModels = new Set((accuracy?.results ?? []).map((r) => r.selected_model).filter(Boolean));

  return (
    <section aria-label={t("financial.forecast.methodsHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("financial.forecast.methodsHeading")}
      </h2>

      {loading ? (
        <Skeleton className="h-40 w-full" />
      ) : !methods || methods.methods.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.insufficientDataTitle")}
          description={t("financial.forecast.insufficientDataDescription")}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {FORECAST_MODEL_NAMES.map((name) => {
            const isSelected = selectedModels.has(name);
            const method = methods.methods.find((m) => m.method === name);
            return (
              <div
                key={name}
                className={`rounded-2xl border p-4 shadow-sm ${
                  isSelected ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white"
                }`}
              >
                <h3 className="text-sm font-semibold text-slate-900">{t(`financial.forecast.method.${name}`)}</h3>
                <p className="mt-1 text-xs text-slate-500">{t(`financial.forecast.methodDescription.${name}`)}</p>
                {method ? (
                  <p className="mt-2 text-xs text-slate-400">
                    {t("financial.forecast.minimumHistory", { count: String(method.minimum_observations_required) })}
                  </p>
                ) : null}
                {isSelected ? (
                  <p className="mt-2 text-xs font-medium text-emerald-700">{t("financial.forecast.selectedModel")}</p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
