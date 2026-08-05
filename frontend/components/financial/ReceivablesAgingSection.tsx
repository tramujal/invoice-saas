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
import type { FinancialAgingBucketName, ReceivablesAgingResponse } from "@/lib/types";

const BUCKET_ORDER: FinancialAgingBucketName[] = [
  "not_yet_due",
  "overdue_1_30",
  "overdue_31_60",
  "overdue_61_90",
  "overdue_90_plus",
];

const BUCKET_BAR_CLASS: Record<FinancialAgingBucketName, string> = {
  not_yet_due: "bg-emerald-500",
  overdue_1_30: "bg-amber-400",
  overdue_31_60: "bg-orange-500",
  overdue_61_90: "bg-red-500",
  overdue_90_plus: "bg-red-800",
};

type ReceivablesAgingSectionProps = {
  aging: ReceivablesAgingResponse | null;
  loading: boolean;
};

/** Section 3 -- AR aging buckets (amount, invoice count, percent of that
 * currency's total open receivables) plus the largest overdue customers.
 * Grouped by currency throughout -- never a cross-currency total. */
export function ReceivablesAgingSection({ aging, loading }: ReceivablesAgingSectionProps) {
  const { t } = useTranslation();

  const currencies = Array.from(new Set((aging?.buckets ?? []).map((b) => b.currency_code))).sort();

  const bucketLabel = (bucket: FinancialAgingBucketName) => t(`financial.aging.${bucket}`);

  return (
    <section aria-label={t("financial.receivablesHeading")} className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.receivablesHeading")}</h2>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : currencies.length === 0 && (!aging || aging.invoices_missing_due_date === 0) ? (
        // Real empty state ONLY when there are truly zero open invoices --
        // an org whose open invoices simply have no due date on file
        // (aging.invoices_missing_due_date > 0) still has real receivables
        // and must never be told "no open receivables" (see the note
        // rendered below instead in that case).
        <EmptyState title={t("financial.receivablesEmptyTitle")} description={t("financial.receivablesEmptyDescription")} />
      ) : (
        <>
          {currencies.map((code) => {
            const bucketsForCurrency = (aging?.buckets ?? []).filter((b) => b.currency_code === code);
            const byBucket = new Map(bucketsForCurrency.map((b) => [b.bucket, b]));
            return (
              <div key={code} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
                {currencies.length > 1 ? (
                  <h3 className="mb-3 text-sm font-semibold text-slate-600">{code}</h3>
                ) : null}
                <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
                  {BUCKET_ORDER.map((bucket) => {
                    const b = byBucket.get(bucket);
                    const percent = b?.percent_of_total ? Number(b.percent_of_total) : 0;
                    if (percent <= 0) return null;
                    return (
                      <div
                        key={bucket}
                        className={BUCKET_BAR_CLASS[bucket]}
                        style={{ width: `${percent}%` }}
                        title={`${bucketLabel(bucket)}: ${percent.toFixed(1)}%`}
                      />
                    );
                  })}
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {BUCKET_ORDER.map((bucket) => {
                    const b = byBucket.get(bucket);
                    return (
                      <div key={bucket} className="rounded-xl border border-slate-200 px-3 py-2.5">
                        <dt className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                          <span className={`h-2 w-2 rounded-full ${BUCKET_BAR_CLASS[bucket]}`} aria-hidden />
                          {bucketLabel(bucket)}
                        </dt>
                        <dd className="mt-1 text-sm font-semibold text-slate-900">
                          {code} {formatMoney(b ? Number(b.amount) : 0)}
                        </dd>
                        <dd className="text-xs text-slate-500">
                          {t("financial.agingInvoiceCount", { count: String(b?.invoice_count ?? 0) })}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </div>
            );
          })}

          {aging && aging.invoices_missing_due_date > 0 ? (
            <p
              className={
                currencies.length === 0
                  ? "rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
                  : "text-xs text-slate-500"
              }
            >
              {t("financial.invoicesMissingDueDate", { count: String(aging.invoices_missing_due_date) })}
            </p>
          ) : null}

          <div className={TABLE_WRAPPER_CLASS}>
            <div className="overflow-x-auto">
              <table className={TABLE_CLASS}>
                <thead className={TABLE_HEAD_CLASS}>
                  <tr>
                    <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colCustomer")}</th>
                    <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colOverdueTotal")}</th>
                    <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colInvoiceCount")}</th>
                    <th className={TABLE_HEAD_CELL_CLASS}>{t("financial.colOldestOverdue")}</th>
                  </tr>
                </thead>
                <tbody className={TABLE_BODY_CLASS}>
                  {(aging?.top_overdue_customers ?? []).length === 0 ? (
                    <tr>
                      <td className={TABLE_CELL_CLASS} colSpan={4}>
                        {t("financial.noOverdueCustomers")}
                      </td>
                    </tr>
                  ) : (
                    (aging?.top_overdue_customers ?? []).map((c) => (
                      <tr key={c.customer_id} className={TABLE_ROW_CLASS}>
                        <td className={TABLE_CELL_CLASS}>{c.customer_name}</td>
                        <td className={TABLE_CELL_CLASS}>
                          {c.currency_code} {formatMoney(Number(c.overdue_total))}
                        </td>
                        <td className={TABLE_CELL_CLASS}>{c.overdue_invoice_count}</td>
                        <td className={TABLE_CELL_CLASS}>
                          {t("financial.daysOverdue", { count: String(c.oldest_overdue_days) })}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
