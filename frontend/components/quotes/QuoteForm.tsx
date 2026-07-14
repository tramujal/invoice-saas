"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationCurrency } from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency, formatMoney, parseQuantity, parseUnitPrice, roundMoney } from "@/lib/money";
import {
  CURRENCY_CODES,
  getCurrencyLabel,
  resolveDefaultInvoiceCurrency,
  type CurrencyCode,
} from "@/lib/organization-settings";
import type { Customer, PaginatedProducts, Product, Quote } from "@/lib/types";

function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

type LineDraft = {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  product_id: string | null;
};

function newLineId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `line-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function defaultLine(id: string = newLineId()): LineDraft {
  return { id, description: "", quantity: "1", unit_price: "0", product_id: null };
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

export function QuoteForm({ mode, initialQuote, backHref, onSubmit, isSubmitting }: QuoteFormProps) {
  const { t } = useTranslation();

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [customerId, setCustomerId] = useState<string>(initialQuote?.customer_id ?? "");
  const [taxPercent, setTaxPercent] = useState<string>(
    initialQuote ? String(Number(initialQuote.tax_rate) * 100) : "0"
  );
  const [taxManuallySet, setTaxManuallySet] = useState(mode === "edit");

  const [products, setProducts] = useState<Product[]>([]);
  useEffect(() => {
    apiFetch<PaginatedProducts>(`${orgPath("products")}?active=true&limit=100`)
      .then((res) => setProducts(res.items))
      .catch(() => setProducts([]));
  }, []);

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

  const [currencyCode, setCurrencyCode] = useState<CurrencyCode>(
    (initialQuote?.currency_code as CurrencyCode) ?? "USD"
  );
  const [currencyManuallySet, setCurrencyManuallySet] = useState(mode === "edit");
  useEffect(() => {
    if (currencyManuallySet) return;
    setCurrencyCode(resolveDefaultInvoiceCurrency(selectedCustomer, orgCurrency));
  }, [selectedCustomer, orgCurrency, currencyManuallySet]);

  // Line ids at first render must be stable across the server and client
  // render passes (not crypto.randomUUID()) -- they're used as real DOM
  // id/list attributes below (the product datalist), so two different
  // random values would be a genuine React hydration mismatch. A plain
  // index-derived id is fine here since uniqueness only needs to hold
  // among rows simultaneously in the DOM; newLineId() (random) is still
  // used for rows added later via addLine(), which only ever runs
  // client-side in response to a click, after hydration has completed.
  const [lines, setLines] = useState<LineDraft[]>(
    initialQuote
      ? initialQuote.line_items.map((li, index) => ({
          id: `initial-line-${index}`,
          description: li.description,
          quantity: li.quantity,
          unit_price: li.unit_price,
          product_id: li.product_id,
        }))
      : [defaultLine("initial-line-0")]
  );

  const issueDate = useMemo(() => initialQuote?.issue_date ?? todayDateString(), [initialQuote]);
  const [expiryDate, setExpiryDate] = useState<string>(initialQuote?.expiry_date ?? "");
  const [notes, setNotes] = useState<string>(initialQuote?.notes ?? "");

  const [submitError, setSubmitError] = useState<string | null>(null);

  const taxRateFraction = useMemo(() => {
    const p = Number(taxPercent);
    if (!Number.isFinite(p) || p < 0) return 0;
    return Math.min(p, 100) / 100;
  }, [taxPercent]);

  const { lineAmounts, subtotal, taxAmount, total } = useMemo(() => {
    const lineAmounts = lines.map((line) => {
      const qty = parseQuantity(line.quantity);
      const price = parseUnitPrice(line.unit_price);
      if (qty === null || price === null) return null;
      return roundMoney(qty * price);
    });

    const sub = lineAmounts.every((v) => v !== null)
      ? roundMoney((lineAmounts as number[]).reduce((acc, v) => roundMoney(acc + v), 0))
      : null;

    const tax = sub !== null ? roundMoney(sub * taxRateFraction) : null;
    const tot = sub !== null && tax !== null ? roundMoney(sub + tax) : null;

    return { lineAmounts, subtotal: sub, taxAmount: tax, total: tot };
  }, [lines, taxRateFraction]);

  function updateLine(id: string, patch: Partial<Omit<LineDraft, "id">>) {
    setLines((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  const productsForCurrency = useMemo(
    () => products.filter((p) => p.currency_code === currencyCode),
    [products, currencyCode]
  );

  function maybePrefillTaxFromLines(candidateLines: LineDraft[]) {
    if (taxManuallySet) return;
    const rates = new Set(
      candidateLines
        .map((l) => products.find((p) => p.id === l.product_id)?.default_tax_rate)
        .filter((r): r is string => r !== undefined)
    );
    if (rates.size === 1) {
      const rate = Number(Array.from(rates)[0]);
      if (Number.isFinite(rate)) setTaxPercent(String(rate * 100));
    }
  }

  function selectProduct(lineId: string, product: Product) {
    setLines((prev) => {
      const next = prev.map((row) =>
        row.id === lineId
          ? { ...row, description: product.name, unit_price: product.default_unit_price, product_id: product.id }
          : row
      );
      maybePrefillTaxFromLines(next);
      return next;
    });
  }

  function handleDescriptionChange(lineId: string, value: string) {
    const matched = productsForCurrency.find((p) => p.name === value);
    if (matched) {
      selectProduct(lineId, matched);
    } else {
      updateLine(lineId, { description: value, product_id: null });
    }
  }

  function addLine() {
    setLines((prev) => [...prev, defaultLine()]);
  }

  function removeLine(id: string) {
    setLines((prev) => (prev.length <= 1 ? prev : prev.filter((r) => r.id !== id)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);

    const parsedLines = lines.map((line) => {
      const description = line.description.trim();
      const quantity = parseQuantity(line.quantity);
      const unit_price = parseUnitPrice(line.unit_price);
      return { description, quantity, unit_price, product_id: line.product_id };
    });

    for (const row of parsedLines) {
      if (!row.description) {
        setSubmitError(t("quoteForm.errorDescriptionRequired"));
        return;
      }
      if (row.quantity === null) {
        setSubmitError(t("quoteForm.errorQuantityInvalid"));
        return;
      }
      if (row.unit_price === null) {
        setSubmitError(t("quoteForm.errorUnitPriceInvalid"));
        return;
      }
    }

    if (expiryDate && expiryDate < issueDate) {
      setSubmitError(t("quoteForm.errorExpiryDateBeforeToday"));
      return;
    }

    await onSubmit({
      customer_id: customerId || null,
      currency_code: currencyCode,
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

          <div className="mt-4 max-w-xs">
            <label htmlFor="currency" className="text-sm font-medium text-slate-700">
              {t("common.currencyLabel")}
            </label>
            <select
              id="currency"
              value={currencyCode}
              onChange={(e) => {
                setCurrencyCode(e.target.value as CurrencyCode);
                setCurrencyManuallySet(true);
              }}
              disabled={isSubmitting}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            >
              {CURRENCY_CODES.map((code) => (
                <option key={code} value={code}>
                  {getCurrencyLabel(t, code)}
                </option>
              ))}
            </select>
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

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("quoteForm.lineItemsSectionTitle")}
            </h2>
            <button
              type="button"
              onClick={addLine}
              disabled={isSubmitting}
              className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-100 disabled:cursor-not-allowed"
            >
              {t("quoteForm.addLine")}
            </button>
          </div>

          <div className="mt-4 space-y-4">
            {lines.map((line, index) => (
              <div key={line.id} className="rounded-xl border border-slate-100 bg-slate-50/60 p-3 sm:p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {t("quoteForm.lineLabel", { number: index + 1 })}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeLine(line.id)}
                    disabled={isSubmitting || lines.length <= 1}
                    className="text-xs font-medium text-red-600 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {t("common.remove")}
                  </button>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-12 sm:gap-4">
                  <div className="sm:col-span-5">
                    <label className="text-xs font-medium text-slate-600">{t("quoteForm.descriptionLabel")}</label>
                    <input
                      type="text"
                      list={`quote-product-options-${line.id}`}
                      value={line.description}
                      onChange={(e) => handleDescriptionChange(line.id, e.target.value)}
                      disabled={isSubmitting}
                      className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                      placeholder={t("quoteForm.descriptionPlaceholder")}
                      autoComplete="off"
                    />
                    <datalist id={`quote-product-options-${line.id}`}>
                      {productsForCurrency.map((p) => (
                        <option key={p.id} value={p.name} />
                      ))}
                    </datalist>
                    {line.product_id ? (
                      <p className="mt-1 text-xs text-slate-500">{t("quoteForm.productLinkedNote")}</p>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-2 gap-3 sm:col-span-4 sm:grid-cols-2">
                    <div>
                      <label className="text-xs font-medium text-slate-600">{t("quoteForm.qtyLabel")}</label>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.0001"
                        value={line.quantity}
                        onChange={(e) => updateLine(line.id, { quantity: e.target.value })}
                        disabled={isSubmitting}
                        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-slate-600">{t("quoteForm.unitPriceLabel")}</label>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={line.unit_price}
                        onChange={(e) => updateLine(line.id, { unit_price: e.target.value })}
                        disabled={isSubmitting}
                        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                      />
                    </div>
                  </div>
                  <div className="sm:col-span-3">
                    <label className="text-xs font-medium text-slate-600">{t("quoteForm.lineTotalLabel")}</label>
                    <div className="mt-1 flex h-[42px] items-center rounded-lg border border-dashed border-slate-200 bg-white px-3 text-sm font-medium text-slate-900">
                      {lineAmounts[index] === null ? "—" : formatMoney(lineAmounts[index] as number)}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

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
                onChange={(e) => {
                  setTaxPercent(e.target.value);
                  setTaxManuallySet(true);
                }}
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
                  {subtotal === null ? "—" : formatCurrency(subtotal, currencyCode)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-600">{t("invoices.colTax")}</dt>
                <dd className="font-medium text-slate-900">
                  {taxAmount === null ? "—" : formatCurrency(taxAmount, currencyCode)}
                </dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-slate-200 pt-3 text-base">
                <dt className="font-semibold text-slate-800">{t("invoices.colTotal")}</dt>
                <dd className="font-semibold text-slate-900">
                  {total === null ? "—" : formatCurrency(total, currencyCode)}
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
