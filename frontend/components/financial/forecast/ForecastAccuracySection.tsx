"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  TABLE_BODY_CLASS,
  TABLE_CELL_CLASS,
  TABLE_CLASS,
  TABLE_HEAD_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_WRAPPER_CLASS,
} from "@/components/ui/TableShell";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { ForecastAccuracyResponse } from "@/lib/types";

type Props = {
  data: ForecastAccuracyResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

/** Section: Forecast Accuracy -- every candidate model's rolling-origin
 * backtest metrics (MAE, WAPE, MAPE-when-safe, directional accuracy), so
 * a user can see not just which model won, but why the other three
 * weren't chosen (or weren't even eligible). See
 * app.financial_intelligence.backtesting.ModelEvaluation. */
export function ForecastAccuracySection({ data, loading, planRestricted }: Props) {
  const { t } = useTranslation();
  if (planRestricted) return null;

  return (
    <section aria-label={t("financial.forecast.accuracyHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("financial.forecast.accuracyHeading")}
      </h2>

      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : !data || data.results.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.insufficientDataTitle")}
          description={t("financial.forecast.insufficientDataDescription")}
        />
      ) : (
        data.results.map((result) => (
          <div key={result.currency_code} className="space-y-2">
            <h3 className="text-sm font-semibold text-slate-600">{result.currency_code}</h3>
            <div className={TABLE_WRAPPER_CLASS}>
              <div className="overflow-x-auto">
                <table className={TABLE_CLASS}>
                  <thead className={TABLE_HEAD_CLASS}>
                    <tr>
                      <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colModel")}</th>
                      <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colMae")}</th>
                      <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colWape")}</th>
                      <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colMape")}</th>
                      <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colDirectionalAccuracy")}</th>
                    </tr>
                  </thead>
                  <tbody className={TABLE_BODY_CLASS}>
                    {result.evaluations.map((entry) => (
                      <tr
                        key={entry.method}
                        className={`${TABLE_ROW_CLASS} ${entry.selected ? "bg-emerald-50/60" : ""}`}
                      >
                        <td className={TABLE_CELL_CLASS}>
                          {t(`financial.forecast.method.${entry.method}`)}
                          {entry.selected ? (
                            <span className="ml-2 text-xs font-medium text-emerald-700">
                              {t("financial.forecast.selectedModel")}
                            </span>
                          ) : !entry.eligible ? (
                            <span className="ml-2 text-xs text-slate-400">
                              {t("financial.forecast.notEligible")}
                            </span>
                          ) : null}
                        </td>
                        <td className={TABLE_CELL_CLASS}>{entry.mae ?? "—"}</td>
                        <td className={TABLE_CELL_CLASS}>{entry.wape !== null ? `${entry.wape}%` : "—"}</td>
                        <td className={TABLE_CELL_CLASS}>{entry.mape !== null ? `${entry.mape}%` : "—"}</td>
                        <td className={TABLE_CELL_CLASS}>
                          {entry.directional_accuracy_percent !== null ? `${entry.directional_accuracy_percent}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ))
      )}
    </section>
  );
}
