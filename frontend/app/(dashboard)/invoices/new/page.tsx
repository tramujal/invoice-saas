"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationCurrency } from "@/lib/auth-storage";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  formatMoney,
  parseQuantity,
  parseUnitPrice,
  roundMoney,
} from "@/lib/money";
import type { Customer, InvoiceCreatedResponse } from "@/lib/types";

type LineDraft = {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
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
  // Read on the client only, after hydration — see invoices/page.tsx for why.
  const [currencyCode, setCurrencyCode] = useState("USD");
  useEffect(() => {
    setCurrencyCode(getOrganizationCurrency() ?? "USD");
  }, []);
  const [lines, setLines] = useState<LineDraft[]>([
    {
      id: newLineId(),
      description: "",
      quantity: "1",
      unit_price: "0",
    },
  ]);

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

  function addLine() {
    setLines((prev) => [
      ...prev,
      {
        id: newLineId(),
        description: "",
        quantity: "1",
        unit_price: "0",
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
      return { description, quantity, unit_price };
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

    const payload: Record<string, unknown> = {
      line_items: parsedLines.map((r) => ({
        description: r.description,
        quantity: r.quantity,
        unit_price: r.unit_price,
      })),
      tax_rate: taxRateFraction,
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
      toast.error(formatApiError(err, t("invoiceForm.toastCreateError")));
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
                      value={line.description}
                      onChange={(e) =>
                        updateLine(line.id, { description: e.target.value })
                      }
                      disabled={isSubmitting}
                      className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2"
                      placeholder={t("invoiceForm.descriptionPlaceholder")}
                      autoComplete="off"
                    />
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
                onChange={(e) => setTaxPercent(e.target.value)}
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
                  {subtotal === null ? "—" : `${currencyCode} ${formatMoney(subtotal)}`}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-600">{t("invoices.colTax")}</dt>
                <dd className="font-medium text-slate-900">
                  {taxAmount === null ? "—" : `${currencyCode} ${formatMoney(taxAmount)}`}
                </dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-slate-200 pt-3 text-base">
                <dt className="font-semibold text-slate-800">{t("invoices.colTotal")}</dt>
                <dd className="font-semibold text-slate-900">
                  {total === null ? "—" : `${currencyCode} ${formatMoney(total)}`}
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
