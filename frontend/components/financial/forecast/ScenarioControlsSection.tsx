"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { ForecastScenarioName, ScenarioResponse } from "@/lib/types";

const SCENARIOS: ForecastScenarioName[] = ["base", "optimistic", "conservative"];

type Props = {
  scenario: ForecastScenarioName;
  onScenarioChange: (scenario: ForecastScenarioName) => void;
  invoiceGrowthPercent: number;
  onInvoiceGrowthPercentChange: (value: number) => void;
  collectionDelayDays: number;
  onCollectionDelayDaysChange: (value: number) => void;
  quoteConversionDeltaPercent: number;
  onQuoteConversionDeltaPercentChange: (value: number) => void;
  data: ScenarioResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

/** Section: Scenario Controls -- Base/Optimistic/Conservative presets,
 * each further adjustable via 3 user-editable assumptions (invoice
 * growth %, collection delay days, quote conversion delta %). Every
 * change re-runs the SAME deterministic math server-side
 * (app.financial_intelligence.forecasting.evaluate_scenario) -- never
 * mutates stored business data, purely a recomputation of the existing
 * forecast with multipliers layered on top. */
export function ScenarioControlsSection({
  scenario,
  onScenarioChange,
  invoiceGrowthPercent,
  onInvoiceGrowthPercentChange,
  collectionDelayDays,
  onCollectionDelayDaysChange,
  quoteConversionDeltaPercent,
  onQuoteConversionDeltaPercentChange,
  data,
  loading,
  planRestricted,
}: Props) {
  const { t } = useTranslation();
  if (planRestricted) return null;

  return (
    <section aria-label={t("financial.forecast.scenariosHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("financial.forecast.scenariosHeading")}
      </h2>

      <div className="flex flex-wrap gap-2" role="group" aria-label={t("financial.forecast.scenariosHeading")}>
        {SCENARIOS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onScenarioChange(s)}
            aria-pressed={scenario === s}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              scenario === s ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {t(`financial.forecast.scenario.${s}`)}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <label className="block text-sm">
          <span className="text-xs font-medium text-slate-500">
            {t("financial.forecast.assumptionInvoiceGrowth")}
          </span>
          <input
            type="number"
            value={invoiceGrowthPercent}
            onChange={(e) => onInvoiceGrowthPercentChange(Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
          />
        </label>
        <label className="block text-sm">
          <span className="text-xs font-medium text-slate-500">
            {t("financial.forecast.assumptionCollectionDelay")}
          </span>
          <input
            type="number"
            value={collectionDelayDays}
            onChange={(e) => onCollectionDelayDaysChange(Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
          />
        </label>
        <label className="block text-sm">
          <span className="text-xs font-medium text-slate-500">
            {t("financial.forecast.assumptionQuoteConversion")}
          </span>
          <input
            type="number"
            value={quoteConversionDeltaPercent}
            onChange={(e) => onQuoteConversionDeltaPercentChange(Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
          />
        </label>
      </div>

      {loading ? (
        <Skeleton className="h-32 w-full" />
      ) : !data || data.results.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.insufficientDataTitle")}
          description={t("financial.forecast.insufficientDataDescription")}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {data.results.map((result) => {
            const revenue90d = result.revenue_horizons.find((h) => h.horizon_days === 90);
            const collections90d = result.collections_horizons.find((h) => h.horizon_days === 90);
            return (
              <div key={result.currency_code} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <h3 className="text-sm font-semibold text-slate-600">{result.currency_code}</h3>
                <dl className="mt-2 space-y-1 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-slate-500">{t("financial.forecast.revenue90d")}</dt>
                    <dd className="font-medium text-slate-900">
                      {revenue90d ? formatMoney(Number(revenue90d.forecast_value)) : "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">{t("financial.forecast.collections90d")}</dt>
                    <dd className="font-medium text-slate-900">
                      {collections90d ? formatMoney(Number(collections90d.total_expected)) : "—"}
                    </dd>
                  </div>
                </dl>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
