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
import { formatMoney } from "@/lib/money";
import type { MonthlyProjectionResponse } from "@/lib/types";

import { ForecastConfidenceBadge } from "./ForecastConfidenceBadge";

type Props = {
  data: MonthlyProjectionResponse | null;
  loading: boolean;
  planRestricted: boolean;
};

function downloadCsv(filename: string, rows: string[][]) {
  const csv = rows.map((row) => row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** Section: Projection Table -- the month-by-month expected/lower/upper/
 * confidence table, plus a CSV export (forecast, lower, upper, currency,
 * model isn't per-row here so it's omitted from the row but the file
 * still carries generated_at + a disclaimer on every line, per this
 * phase's export requirement). Built entirely client-side from data
 * already fetched -- no separate export endpoint needed. */
export function ProjectionTableSection({ data, loading, planRestricted }: Props) {
  const { t } = useTranslation();
  if (planRestricted) return null;

  const handleExport = () => {
    if (!data) return;
    const disclaimer = t("financial.forecast.csvDisclaimer");
    const rows: string[][] = [
      ["month", "currency", "forecast", "lower", "upper", "confidence", "generated_at", "disclaimer"],
      ...data.points.map((p) => [
        p.month,
        p.currency_code,
        p.expected_value,
        p.lower_bound,
        p.upper_bound,
        p.confidence,
        data.generated_at,
        disclaimer,
      ]),
    ];
    downloadCsv(`revenue-forecast-${data.generated_at.slice(0, 10)}.csv`, rows);
  };

  return (
    <section aria-label={t("financial.forecast.projectionTableHeading")} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("financial.forecast.projectionTableHeading")}
        </h2>
        {data && data.points.length > 0 ? (
          <button
            type="button"
            onClick={handleExport}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            {t("financial.forecast.exportCsv")}
          </button>
        ) : null}
      </div>

      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : !data || data.points.length === 0 ? (
        <EmptyState
          title={t("financial.forecast.insufficientDataTitle")}
          description={t("financial.forecast.insufficientDataDescription")}
        />
      ) : (
        <div className={TABLE_WRAPPER_CLASS}>
          <div className="overflow-x-auto">
            <table className={TABLE_CLASS}>
              <thead className={TABLE_HEAD_CLASS}>
                <tr>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colMonth")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colCurrency")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colExpected")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colRange")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.forecast.colConfidence")}</th>
                </tr>
              </thead>
              <tbody className={TABLE_BODY_CLASS}>
                {data.points.map((p, i) => (
                  <tr key={`${p.currency_code}-${p.month}-${i}`} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>{p.month}</td>
                    <td className={TABLE_CELL_CLASS}>{p.currency_code}</td>
                    <td className={TABLE_CELL_CLASS}>{formatMoney(Number(p.expected_value))}</td>
                    <td className={TABLE_CELL_CLASS}>
                      {formatMoney(Number(p.lower_bound))} – {formatMoney(Number(p.upper_bound))}
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <ForecastConfidenceBadge confidence={p.confidence} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
