"use client";

import { EmptyState } from "@/components/ui/EmptyState";
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
import type { AnalyticsRevenueBreakdown } from "@/lib/types";

type RevenueBreakdownSectionProps = {
  revenueBreakdown: AnalyticsRevenueBreakdown[];
  averageInvoiceValue: Record<string, string>;
  loading: boolean;
};

/** Deliberately a table, not a chart: with 1-2 currencies a chart would be
 * fine, but a chart that tries to represent 3+ independent currencies at
 * once either stacks incompatible units together or forces a separate
 * chart per currency -- a plain table scales to any currency count without
 * ever implying a total across currencies exists. Every row here already
 * arrives fully computed from GET /analytics/kpis; nothing is summed or
 * derived client-side. */
export function RevenueBreakdownSection({
  revenueBreakdown,
  averageInvoiceValue,
  loading,
}: RevenueBreakdownSectionProps) {
  const { t } = useTranslation();

  return (
    <section aria-label={t("analytics.revenueHeading")} className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("analytics.revenueHeading")}
      </h2>

      {loading ? (
        <div className="h-40 w-full animate-pulse rounded-2xl bg-slate-100" />
      ) : revenueBreakdown.length === 0 ? (
        <EmptyState
          title={t("analytics.revenueEmptyTitle")}
          description={t("analytics.revenueEmptyDescription")}
        />
      ) : (
        <div className={TABLE_WRAPPER_CLASS}>
          <div className="overflow-x-auto">
            <table className={TABLE_CLASS}>
              <thead className={TABLE_HEAD_CLASS}>
                <tr>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("analytics.revenueColCurrency")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("analytics.revenueColTotal")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("analytics.revenueColPaid")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("analytics.revenueColOutstanding")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("analytics.revenueColOverdue")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("analytics.revenueColAvgInvoice")}</th>
                </tr>
              </thead>
              <tbody className={TABLE_BODY_CLASS}>
                {revenueBreakdown.map((row) => (
                  <tr key={row.currency_code} className={TABLE_ROW_CLASS}>
                    <td className={`${TABLE_CELL_CLASS} font-semibold text-slate-900`}>
                      {row.currency_code}
                    </td>
                    <td className={TABLE_CELL_CLASS}>{formatMoney(Number.parseFloat(row.total))}</td>
                    <td className={TABLE_CELL_CLASS}>{formatMoney(Number.parseFloat(row.paid))}</td>
                    <td className={TABLE_CELL_CLASS}>
                      {formatMoney(Number.parseFloat(row.outstanding))}
                    </td>
                    <td className={TABLE_CELL_CLASS}>{formatMoney(Number.parseFloat(row.overdue))}</td>
                    <td className={TABLE_CELL_CLASS}>
                      {averageInvoiceValue[row.currency_code] !== undefined
                        ? formatMoney(Number.parseFloat(averageInvoiceValue[row.currency_code]))
                        : "—"}
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
