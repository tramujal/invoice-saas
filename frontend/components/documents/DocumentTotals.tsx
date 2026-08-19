"use client";

import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency, formatMoney } from "@/lib/money";
import type { CurrencyCode } from "@/lib/organization-settings";
import type { TaxGroupSummary } from "@/lib/use-document-lines";

/** The totals panel for the invoice and quote forms (Phase 28).
 *
 * Replaces the single document-level "Tax rate %" input both forms used
 * to carry -- tax now lives on each line, so a document-wide field would
 * be a second, contradictory source of truth.
 *
 * When rates differ, every bucket is listed with its taxable BASE, so
 * the reader can reconstruct the arithmetic. The exempt bucket is
 * labelled "Exempt", never "Tax 0%": no tax was applied to those lines,
 * and showing a 0.00 in a tax column would imply otherwise.
 */
export function DocumentTotals({
  subtotal,
  taxGroups,
  taxAmount,
  total,
  documentCurrency,
}: {
  subtotal: number | null;
  taxGroups: TaxGroupSummary[];
  taxAmount: number | null;
  total: number | null;
  documentCurrency: CurrencyCode | null;
}) {
  const { t } = useTranslation();

  const money = (value: number | null) =>
    value === null
      ? "—"
      : documentCurrency
        ? formatCurrency(value, documentCurrency)
        : formatMoney(value);

  const mixed = taxGroups.length > 1;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <div className="flex justify-end">
        <dl className="w-full space-y-3 rounded-xl bg-slate-50 p-4 text-sm sm:max-w-md sm:p-5">
          <div className="flex justify-between gap-4">
            <dt className="text-slate-600">{t("invoices.colSubtotal")}</dt>
            <dd className="font-medium text-slate-900">{money(subtotal)}</dd>
          </div>

          {mixed ? (
            taxGroups.map((group) => (
              <div key={group.percent} className="flex justify-between gap-4">
                <dt className="text-slate-600">
                  {group.percent === "0"
                    ? t("documentTotals.exemptLabel")
                    : `${t("invoices.colTax")} ${group.percent}%`}
                  <span className="ml-1 text-xs text-slate-400">
                    ({t("documentTotals.baseLabel")} {money(group.base)})
                  </span>
                </dt>
                <dd className="font-medium text-slate-900">{money(group.tax)}</dd>
              </div>
            ))
          ) : (
            <div className="flex justify-between gap-4">
              <dt className="text-slate-600">{t("invoices.colTax")}</dt>
              <dd className="font-medium text-slate-900">{money(taxAmount)}</dd>
            </div>
          )}

          {mixed ? (
            <div className="flex justify-between gap-4 border-t border-slate-200 pt-3">
              <dt className="text-slate-600">{t("documentTotals.totalTaxLabel")}</dt>
              <dd className="font-medium text-slate-900">{money(taxAmount)}</dd>
            </div>
          ) : null}

          <div className="flex justify-between gap-4 border-t border-slate-200 pt-3 text-base">
            <dt className="font-semibold text-slate-800">{t("invoices.colTotal")}</dt>
            <dd className="font-semibold text-slate-900">{money(total)}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
