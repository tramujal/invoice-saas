"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationCurrency } from "@/lib/auth-storage";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  formatCurrency,
  formatMoney,
  parseQuantity,
  parseUnitPrice,
  roundMoney,
} from "@/lib/money";
import {
  PAYMENT_TERMS_PRESETS,
  computeDueDate,
  getPaymentTermsLabel,
  type PaymentTermsPresetKey,
} from "@/lib/invoice-due-date";
import {
  CURRENCY_CODES,
  getCurrencyLabel,
  resolveDefaultInvoiceCurrency,
  type CurrencyCode,
} from "@/lib/organization-settings";
import type { Customer, InvoiceCreatedResponse, PaginatedProducts, Product } from "@/lib/types";

function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

type LineDraft = {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  // A pure analytics tag ("this line came from this catalog item") -- see
  // InvoiceLineItemCreate.product_id. Cleared the moment the description
  // no longer matches the linked product's name, since at that point it's
  // effectively a different, manually-described line.
  product_id: string | null;
};

function newLineId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `line-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function NewInvoicePage() {
  const router = useRouter();
  const toast = useToast();
  const { t } = useTranslation();

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [customerId, setCustomerId] = useState<string>("");
  const [taxPercent, setTaxPercent] = useState<string>("0");
  // Once the user edits tax by hand, auto-prefilling from a selected
  // product's default_tax_rate stops -- same "manually set" gating already
  // used for currencyManuallySet below.
  const [taxManuallySet, setTaxManuallySet] = useState(false);

  const [products, setProducts] = useState<Product[]>([]);
  useEffect(() => {
    apiFetch<PaginatedProducts>(`${orgPath("products")}?active=true&limit=100`)
      .then((res) => setProducts(res.items))
      .catch(() => setProducts([]));
  }, []);

  // Read on the client only, after hydration — see invoices/page.tsx for why.
  const [orgCurrency, setOrgCurrency] = useState<string | null>(null);
  useEffect(() => {
    setOrgCurrency(getOrganizationCurrency());
  }, []);

  const selectedCustomer = customers.find((c) => c.id === customerId) ?? null;

  // Defaults to resolveDefaultInvoiceCurrency(selectedCustomer, orgCurrency)
  // — today that's always just the org's currency (Customer has no
  // preferred-currency field yet), but recomputing this whenever the
  // selected customer changes, gated by currencyManuallySet, is exactly the
  // wiring a future customer-preferred-currency needs: only
  // resolveDefaultInvoiceCurrency's body would have to change. Once the
  // user manually picks a currency, auto-defaulting stops so their choice
  // always wins, per invoice, regardless of further customer changes.
  const [currencyCode, setCurrencyCode] = useState<CurrencyCode>("USD");
  const [currencyManuallySet, setCurrencyManuallySet] = useState(false);
  useEffect(() => {
    if (currencyManuallySet) return;
    setCurrencyCode(resolveDefaultInvoiceCurrency(selectedCustomer, orgCurrency));
  }, [selectedCustomer, orgCurrency, currencyManuallySet]);
  // A stable, non-random id here (not newLineId()) -- this line exists at
  // first render, which happens once on the server and again on the
  // client during hydration; a random id would differ between the two
  // passes and mismatch against the real DOM id/list attributes used
  // below (the product datalist). newLineId() is still used for every
  // line added later via addLine(), which only ever runs client-side in
  // response to a click, after hydration has already completed.
  const [lines, setLines] = useState<LineDraft[]>([
    {
      id: "initial-line-0",
      description: "",
      quantity: "1",
      unit_price: "0",
      product_id: null,
    },
  ]);

  const issueDate = useMemo(() => todayDateString(), []);
  const [paymentTermsKey, setPaymentTermsKey] = useState<PaymentTermsPresetKey>("onReceipt");
  const [dueDate, setDueDate] = useState<string>(issueDate);
  const [customDueDate, setCustomDueDate] = useState<string>(issueDate);

  function onPaymentTermsChange(key: PaymentTermsPresetKey) {
    setPaymentTermsKey(key);
    const preset = PAYMENT_TERMS_PRESETS.find((p) => p.key === key);
    if (preset && preset.days !== null) {
      setDueDate(computeDueDate(issueDate, preset.days));
    } else {
      setDueDate(customDueDate);
    }
  }

  function onCustomDueDateChange(value: string) {
    setCustomDueDate(value);
    setDueDate(value);
  }

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadCustomers = useCallback(async () => {
    setCustomersLoading(true);
    try {
      const rows = await apiFetch<Customer[]>(orgPath("customers"));
      setCustomers(rows);
    } catch {
      setCustomers([]);
    } finally {
      setCustomersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCustomers();
  }, [loadCustomers]);

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
      ? roundMoney(
          (lineAmounts as number[]).reduce((acc, v) => roundMoney(acc + v), 0)
        )
      : null;

    const tax =
      sub !== null ? roundMoney(sub * taxRateFraction) : null;
    const tot = sub !== null && tax !== null ? roundMoney(sub + tax) : null;

    return {
      lineAmounts,
      subtotal: sub,
      taxAmount: tax,
      total: tot,
    };
  }, [lines, taxRateFraction]);

  function updateLine(id: string, patch: Partial<Omit<LineDraft, "id">>) {
    setLines((prev) =>
      prev.map((row) => (row.id === id ? { ...row, ...patch } : row))
    );
  }

  // Only products in the invoice's own currency are ever offered -- this
  // app never mixes currencies, and picking a customer never changes the
  // invoice's currency either, so a product picker in a different
  // currency simply isn't a match for this invoice (see the plan's
  // "products are single-currency, like invoices" decision).
  const productsForCurrency = useMemo(
    () => products.filter((p) => p.currency_code === currencyCode),
    [products, currencyCode]
  );

  // Prefills the invoice's single tax-rate field from a product's
  // default_tax_rate, but only while every product line added so far
  // shares one rate and the user hasn't touched tax manually -- the
  // moment either stops being true, this simply does nothing further,
  // leaving tax as a normal editable field (see the plan's tax decision).
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
          ? {
              ...row,
              description: product.name,
              unit_price: product.default_unit_price,
              product_id: product.id,
            }
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
    setLines((prev) => [
      ...prev,
      {
        id: newLineId(),
        description: "",
        quantity: "1",
        unit_price: "0",
        product_id: null,
      },
    ]);
  }

  function removeLine(id: string) {
    setLines((prev) => (prev.length <= 1 ? prev : prev.filter((r) => r.id !== id)));
  }

  async function onSubmit(e: React.FormEvent) {
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
        setSubmitError(t("invoiceForm.errorDescriptionRequired"));
        return;
      }
      if (row.quantity === null) {
        setSubmitError(t("invoiceForm.errorQuantityInvalid"));
        return;
      }
      if (row.unit_price === null) {
        setSubmitError(t("invoiceForm.errorUnitPriceInvalid"));
        return;
      }
    }

    if (dueDate && dueDate < issueDate) {
      setSubmitError(t("invoiceForm.errorDueDateBeforeIssueDate"));
      return;
    }

    const payload: Record<string, unknown> = {
      line_items: parsedLines.map((r) => ({
        description: r.description,
        quantity: r.quantity,
        unit_price: r.unit_price,
        product_id: r.product_id,
      })),
      tax_rate: taxRateFraction,
      currency_code: currencyCode,
      due_date: dueDate || null,
    };
    if (customerId) {
      payload.customer_id = customerId;
    }

    const loadingId = toast.loading(t("invoiceForm.toastCreating"));
    setIsSubmitting(true);
    try {
      await apiFetch<InvoiceCreatedResponse>(orgPath("invoices"), {
        method: "POST",
        body: JSON.stringify(payload),
      });
      toast.dismiss(loadingId);
      toast.success(t("invoiceForm.toastCreated"));
      router.push("/invoices");
      router.refresh();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : formatApiError(err, t("invoiceForm.toastCreateError"))
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const disableCustomerSelect = isSubmitting || customersLoading;

  return (
    <div className="mx-auto max-w-4xl space-y-8 pb-12">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Link
            href="/invoices"
            className="text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            {t("invoiceForm.backToInvoices")}
          </Link>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
            {t("invoices.newInvoice")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{t("invoiceForm.subtitle")}</p>
        </div>
      </div>

      <form
        onSubmit={(e) => void onSubmit(e)}
        className="space-y-8"
        aria-busy={isSubmitting}
      >
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("invoiceForm.customerSectionTitle")}
          </h2>
          <div className="mt-4 max-w-xl">
            <label htmlFor="customer" className="text-sm font-medium text-slate-700">
              {t("invoiceForm.billToLabel")}
            </label>
            <select
              id="customer"
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              disabled={disableCustomerSelect}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
            >
              <option value="">{t("invoiceForm.noCustomerOption")}</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} — {c.email}
                </option>
              ))}
            </select>
            {customersLoading ? (
              <p className="mt-2 text-xs text-slate-500">{t("customers.loading")}</p>
            ) : customers.length === 0 ? (
              <p className="mt-2 text-xs text-amber-700">
                {t("invoiceForm.noCustomersMessage")}{" "}
                <Link href="/customers" className="font-medium underline">
                  {t("invoiceForm.createOneFirst")}
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
            {t("invoiceForm.paymentTermsSectionTitle")}
          </h2>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="text-sm font-medium text-slate-700">
                {t("invoiceForm.issueDateLabel")}
              </label>
              <div className="mt-1 flex h-[42px] items-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 text-sm text-slate-700">
                {issueDate}
              </div>
            </div>
            <div>
              <label htmlFor="paymentTerms" className="text-sm font-medium text-slate-700">
                {t("invoiceForm.paymentTermsLabel")}
              </label>
              <select
                id="paymentTerms"
                value={paymentTermsKey}
                onChange={(e) => onPaymentTermsChange(e.target.value as PaymentTermsPresetKey)}
                disabled={isSubmitting}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              >
                {PAYMENT_TERMS_PRESETS.map((preset) => (
                  <option key={preset.key} value={preset.key}>
                    {getPaymentTermsLabel(t, preset.key)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="dueDate" className="text-sm font-medium text-slate-700">
                {t("invoiceForm.dueDateLabel")}
              </label>
              <input
                id="dueDate"
                type="date"
                min={issueDate}
                value={dueDate}
                onChange={(e) => onCustomDueDateChange(e.target.value)}
                disabled={isSubmitting || paymentTermsKey !== "custom"}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2 disabled:bg-slate-50"
              />
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("invoiceForm.lineItemsSectionTitle")}
            </h2>
            <button
              type="button"
              onClick={addLine}
              disabled={isSubmitting}
              className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-100 disabled:cursor-not-allowed"
            >
              {t("invoiceForm.addLine")}
            </button>
          </div>

          <div className="mt-4 space-y-4">
            {lines.map((line, index) => (
              <div
                key={line.id}
                className="rounded-xl border border-slate-100 bg-slate-50/60 p-3 sm:p-4"
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {t("invoiceForm.lineLabel", { number: index + 1 })}
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
                    <label className="text-xs font-medium text-slate-600">
                      {t("invoiceForm.descriptionLabel")}
                    </label>
                    <input
                      type="text"
                      list={`product-options-${line.id}`}
                      value={line.description}
                      onChange={(e) => handleDescriptionChange(line.id, e.target.value)}
                      disabled={isSubmitting}
                      className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                      placeholder={t("invoiceForm.descriptionPlaceholder")}
                      autoComplete="off"
                    />
                    <datalist id={`product-options-${line.id}`}>
                      {productsForCurrency.map((p) => (
                        <option key={p.id} value={p.name} />
                      ))}
                    </datalist>
                    {line.product_id ? (
                      <p className="mt-1 text-xs text-slate-500">
                        {t("invoiceForm.productLinkedNote")}
                      </p>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-2 gap-3 sm:col-span-4 sm:grid-cols-2">
                    <div>
                      <label className="text-xs font-medium text-slate-600">
                        {t("invoiceForm.qtyLabel")}
                      </label>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.0001"
                        value={line.quantity}
                        onChange={(e) =>
                          updateLine(line.id, { quantity: e.target.value })
                        }
                        disabled={isSubmitting}
                        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-slate-600">
                        {t("invoiceForm.unitPriceLabel")}
                      </label>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={line.unit_price}
                        onChange={(e) =>
                          updateLine(line.id, { unit_price: e.target.value })
                        }
                        disabled={isSubmitting}
                        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                      />
                    </div>
                  </div>
                  <div className="sm:col-span-3">
                    <label className="text-xs font-medium text-slate-600">
                      {t("invoiceForm.lineTotalLabel")}
                    </label>
                    <div className="mt-1 flex h-[42px] items-center rounded-lg border border-dashed border-slate-200 bg-white px-3 text-sm font-medium text-slate-900">
                      {lineAmounts[index] === null
                        ? "—"
                        : formatMoney(lineAmounts[index] as number)}
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
                {t("invoiceForm.taxRateLabel")}
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
                {t("invoiceForm.taxRateHelpPrefix")}{" "}
                <code className="rounded bg-slate-100 px-1">{taxRateFraction}</code>{" "}
                {t("invoiceForm.taxRateHelpSuffix")}
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
          <div
            className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            role="alert"
          >
            {submitError}
          </div>
        ) : null}

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Link
            href="/invoices"
            className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-center text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
          >
            {t("common.cancel")}
          </Link>
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting ? (
              <>
                <svg
                  className="h-4 w-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                {t("invoiceForm.submitCreating")}
              </>
            ) : (
              t("invoiceForm.submitCreate")
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
