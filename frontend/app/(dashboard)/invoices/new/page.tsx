"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { LineItemsEditor } from "@/components/documents/LineItemsEditor";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationCurrency } from "@/lib/auth-storage";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency, formatMoney, parseQuantity, parseUnitPrice } from "@/lib/money";
import {
  PAYMENT_TERMS_PRESETS,
  computeDueDate,
  getPaymentTermsLabel,
  type PaymentTermsPresetKey,
} from "@/lib/invoice-due-date";
import { resolveDefaultInvoiceCurrency } from "@/lib/organization-settings";
import { useDocumentLines } from "@/lib/use-document-lines";
import type { Customer, InvoiceCreatedResponse } from "@/lib/types";

function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function NewInvoicePage() {
  const router = useRouter();
  const toast = useToast();
  const { t } = useTranslation();

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [customerId, setCustomerId] = useState<string>("");

  // Read on the client only, after hydration — see invoices/page.tsx for why.
  const [orgCurrency, setOrgCurrency] = useState<string | null>(null);
  useEffect(() => {
    setOrgCurrency(getOrganizationCurrency());
  }, []);

  const selectedCustomer = customers.find((c) => c.id === customerId) ?? null;
  // Only used as the ManualLineEditor's preselected currency when the
  // document has none yet — the document's real currency is always
  // derived from its lines (see useDocumentLines), never chosen upfront.
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
  } = useDocumentLines();

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

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);

    if (lines.length === 0) {
      setSubmitError(t("lineItemPicker.errorAtLeastOneLine"));
      return;
    }

    const parsedLines = lines.map((line) => ({
      description: line.description.trim(),
      quantity: line.quantity,
      unit_price: line.unit_price,
      product_id: line.product_id,
    }));

    for (const row of parsedLines) {
      if (!row.description) {
        setSubmitError(t("lineItemPicker.errorDescriptionRequired"));
        return;
      }
      if (parseQuantity(row.quantity) === null) {
        setSubmitError(t("lineItemPicker.errorQuantityInvalid"));
        return;
      }
      if (parseUnitPrice(row.unit_price) === null) {
        setSubmitError(t("lineItemPicker.errorUnitPriceInvalid"));
        return;
      }
    }

    if (dueDate && dueDate < issueDate) {
      setSubmitError(t("invoiceForm.errorDueDateBeforeIssueDate"));
      return;
    }

    const payload: Record<string, unknown> = {
      line_items: parsedLines,
      tax_rate: taxRateFraction,
      currency_code: documentCurrency,
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
            <Select
              id="customer"
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              disabled={disableCustomerSelect}
              className="mt-1 shadow-sm"
            >
              <option value="">{t("invoiceForm.noCustomerOption")}</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} — {c.email}
                </option>
              ))}
            </Select>
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
              <Select
                id="paymentTerms"
                value={paymentTermsKey}
                onChange={(e) => onPaymentTermsChange(e.target.value as PaymentTermsPresetKey)}
                disabled={isSubmitting}
                className="mt-1 shadow-sm"
              >
                {PAYMENT_TERMS_PRESETS.map((preset) => (
                  <option key={preset.key} value={preset.key}>
                    {getPaymentTermsLabel(t, preset.key)}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <label htmlFor="dueDate" className="text-sm font-medium text-slate-700">
                {t("invoiceForm.dueDateLabel")}
              </label>
              <Input
                id="dueDate"
                type="date"
                min={issueDate}
                value={dueDate}
                onChange={(e) => onCustomDueDateChange(e.target.value)}
                disabled={isSubmitting || paymentTermsKey !== "custom"}
                className="mt-1"
              />
            </div>
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
                {t("invoiceForm.taxRateLabel")}
              </label>
              <Input
                id="tax"
                type="number"
                inputMode="decimal"
                min="0"
                max="100"
                step="0.01"
                value={taxPercent}
                onChange={(e) => onTaxPercentChange(e.target.value)}
                disabled={isSubmitting}
                className="mt-1 max-w-xs sm:max-w-none"
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
          <div
            className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            role="alert"
          >
            {submitError}
          </div>
        ) : null}

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <ButtonLink href="/invoices" variant="secondary">
            {t("common.cancel")}
          </ButtonLink>
          <Button type="submit" disabled={isSubmitting}>
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
          </Button>
        </div>
      </form>
    </div>
  );
}
