"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { LineItemsEditor } from "@/components/documents/LineItemsEditor";
import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationCurrency } from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency, formatMoney, parseQuantity, parseUnitPrice } from "@/lib/money";
import { resolveDefaultInvoiceCurrency, type CurrencyCode } from "@/lib/organization-settings";
import type { Customer, Quote } from "@/lib/types";
import { useDocumentLines, type LineDraft } from "@/lib/use-document-lines";

function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

export type QuoteFormValues = {
  customer_id: string | null;
  currency_code: CurrencyCode;
  line_items: { description: string; quantity: number; unit_price: number; product_id: string | null }[];
  tax_rate: number;
  expiry_date: string | null;
  notes: string;
};

type QuoteFormProps = {
  mode: "create" | "edit";
  initialQuote?: Quote;
  backHref: string;
  onSubmit: (values: QuoteFormValues) => Promise<void>;
  isSubmitting: boolean;
};

/** Seeds each of an existing quote's line items with its own client-only
 * currency_code, set directly from the quote's pinned currency rather than
 * looked up from a products cache -- this form no longer eagerly preloads
 * the product catalog, so a lookup-based fallback would silently fail to
 * resolve currency for essentially every pre-existing product-linked line
 * on initial edit-mode load, not just archived/deleted ones. */
function seedLinesFromQuote(quote: Quote): LineDraft[] {
  const currency = (quote.currency_code as CurrencyCode) ?? "USD";
  return quote.line_items.map((li, index) => ({
    id: `initial-line-${index}`,
    description: li.description,
    quantity: li.quantity,
    unit_price: li.unit_price,
    product_id: li.product_id,
    currency_code: currency,
    default_tax_rate: null,
  }));
}

export function QuoteForm({ mode, initialQuote, backHref, onSubmit, isSubmitting }: QuoteFormProps) {
  const { t } = useTranslation();

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [customerId, setCustomerId] = useState<string>(initialQuote?.customer_id ?? "");

  const [orgCurrency, setOrgCurrency] = useState<string | null>(null);
  useEffect(() => {
    setOrgCurrency(getOrganizationCurrency());
  }, []);

  useEffect(() => {
    setCustomersLoading(true);
    apiFetch<Customer[]>(orgPath("customers"))
      .then((rows) => setCustomers(rows))
      .catch(() => setCustomers([]))
      .finally(() => setCustomersLoading(false));
  }, []);

  const selectedCustomer = customers.find((c) => c.id === customerId) ?? null;
  const defaultCurrency = resolveDefaultInvoiceCurrency(selectedCustomer, orgCurrency);

  const {
    lines,
    documentCurrency,
    addProductLine,
    addManualLine,
    updateLine,
    removeLine,
    taxPercent,
    onTaxPercentChange,
    taxRateFraction,
    lineAmounts,
    subtotal,
    taxAmount,
    total,
  } = useDocumentLines({
    initialLines: initialQuote ? seedLinesFromQuote(initialQuote) : undefined,
    initialTaxPercent: initialQuote ? String(Number(initialQuote.tax_rate) * 100) : undefined,
    taxManuallySetInitially: mode === "edit",
  });

  const issueDate = useMemo(() => initialQuote?.issue_date ?? todayDateString(), [initialQuote]);
  const [expiryDate, setExpiryDate] = useState<string>(initialQuote?.expiry_date ?? "");
  const [notes, setNotes] = useState<string>(initialQuote?.notes ?? "");

  const [submitError, setSubmitError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);

    if (lines.length === 0) {
      setSubmitError(t("lineItemPicker.errorAtLeastOneLine"));
      return;
    }

    const parsedLines = lines.map((line) => {
      const description = line.description.trim();
      const quantity = parseQuantity(line.quantity);
      const unit_price = parseUnitPrice(line.unit_price);
      return { description, quantity, unit_price, product_id: line.product_id };
    });

    for (const row of parsedLines) {
      if (!row.description) {
        setSubmitError(t("lineItemPicker.errorDescriptionRequired"));
        return;
      }
      if (row.quantity === null) {
        setSubmitError(t("lineItemPicker.errorQuantityInvalid"));
        return;
      }
      if (row.unit_price === null) {
        setSubmitError(t("lineItemPicker.errorUnitPriceInvalid"));
        return;
      }
    }

    if (expiryDate && expiryDate < issueDate) {
      setSubmitError(t("quoteForm.errorExpiryDateBeforeToday"));
      return;
    }

    // documentCurrency is guaranteed non-null here: submit is blocked above
    // whenever lines is empty, and a non-empty lines array always has a
    // first line with its own currency_code (see useDocumentLines).
    await onSubmit({
      customer_id: customerId || null,
      currency_code: documentCurrency as CurrencyCode,
      line_items: parsedLines as {
        description: string;
        quantity: number;
        unit_price: number;
        product_id: string | null;
      }[],
      tax_rate: taxRateFraction,
      expiry_date: expiryDate || null,
      notes,
    });
  }

  const disableCustomerSelect = isSubmitting || customersLoading;

  return (
    <div className="mx-auto max-w-4xl space-y-8 pb-12">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Link href={backHref} className="text-sm font-medium text-slate-600 hover:text-slate-900">
            {t("quoteForm.backToQuotes")}
          </Link>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
            {mode === "create" ? t("quotes.newQuote") : t("quoteForm.editTitle")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{t("quoteForm.subtitle")}</p>
        </div>
      </div>

      <form onSubmit={(e) => void handleSubmit(e)} className="space-y-8" aria-busy={isSubmitting}>
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("quoteForm.customerSectionTitle")}
          </h2>
          <div className="mt-4 max-w-xl">
            <label htmlFor="customer" className="text-sm font-medium text-slate-700">
              {t("quoteForm.billToLabel")}
            </label>
            <select
              id="customer"
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              disabled={disableCustomerSelect}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            >
              <option value="">{t("quoteForm.noCustomerOption")}</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} — {c.email}
                </option>
              ))}
            </select>
            {!customersLoading && customers.length === 0 ? (
              <p className="mt-2 text-xs text-amber-700">
                {t("quoteForm.noCustomersMessage")}{" "}
                <Link href="/customers" className="font-medium underline">
                  {t("quoteForm.createOneFirst")}
                </Link>
                .
              </p>
            ) : null}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("quoteForm.detailsSectionTitle")}
          </h2>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="text-sm font-medium text-slate-700">{t("quoteForm.issueDateLabel")}</label>
              <div className="mt-1 flex h-[42px] items-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 text-sm text-slate-700">
                {issueDate}
              </div>
            </div>
            <div>
              <label htmlFor="expiryDate" className="text-sm font-medium text-slate-700">
                {t("quoteForm.expiryDateLabel")}
              </label>
              <input
                id="expiryDate"
                type="date"
                min={issueDate}
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                disabled={isSubmitting}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>
          </div>
          <div className="mt-4">
            <label htmlFor="notes" className="text-sm font-medium text-slate-700">
              {t("quoteForm.notesLabel")}
            </label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={isSubmitting}
              rows={3}
              placeholder={t("quoteForm.notesPlaceholder")}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            />
          </div>
        </section>

        <LineItemsEditor
          lines={lines}
          documentCurrency={documentCurrency}
          defaultCurrency={defaultCurrency}
          lineAmounts={lineAmounts}
          onAddProductLine={addProductLine}
          onAddManualLine={addManualLine}
          onUpdateLine={updateLine}
          onRemoveLine={removeLine}
          disabled={isSubmitting}
        />

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div>
              <label htmlFor="tax" className="text-sm font-medium text-slate-700">
                {t("quoteForm.taxRateLabel")}
              </label>
              <input
                id="tax"
                type="number"
                inputMode="decimal"
                min="0"
                max="100"
                step="0.01"
                value={taxPercent}
                onChange={(e) => onTaxPercentChange(e.target.value)}
                disabled={isSubmitting}
                className="mt-1 w-full max-w-xs rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 sm:max-w-none"
              />
              <p className="mt-1 text-xs text-slate-500">
                {t("quoteForm.taxRateHelpPrefix")} <code className="rounded bg-slate-100 px-1">{taxRateFraction}</code>{" "}
                {t("quoteForm.taxRateHelpSuffix")}
              </p>
            </div>
            <dl className="space-y-3 rounded-xl bg-slate-50 p-4 text-sm sm:p-5">
              <div className="flex justify-between gap-4">
                <dt className="text-slate-600">{t("invoices.colSubtotal")}</dt>
                <dd className="font-medium text-slate-900">
                  {subtotal === null
                    ? "—"
                    : documentCurrency
                      ? formatCurrency(subtotal, documentCurrency)
                      : formatMoney(subtotal)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-600">{t("invoices.colTax")}</dt>
                <dd className="font-medium text-slate-900">
                  {taxAmount === null
                    ? "—"
                    : documentCurrency
                      ? formatCurrency(taxAmount, documentCurrency)
                      : formatMoney(taxAmount)}
                </dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-slate-200 pt-3 text-base">
                <dt className="font-semibold text-slate-800">{t("invoices.colTotal")}</dt>
                <dd className="font-semibold text-slate-900">
                  {total === null
                    ? "—"
                    : documentCurrency
                      ? formatCurrency(total, documentCurrency)
                      : formatMoney(total)}
                </dd>
              </div>
            </dl>
          </div>
        </section>

        {submitError ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {submitError}
          </div>
        ) : null}

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Link
            href={backHref}
            className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-center text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
          >
            {t("common.cancel")}
          </Link>
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {mode === "create"
              ? isSubmitting
                ? t("quoteForm.submitCreating")
                : t("quoteForm.submitCreate")
              : isSubmitting
                ? t("quoteForm.submitSaving")
                : t("quoteForm.submitSave")}
          </button>
        </div>
      </form>
    </div>
  );
}
