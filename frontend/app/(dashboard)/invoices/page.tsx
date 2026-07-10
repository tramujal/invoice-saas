"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PaymentStatusSelect } from "@/components/invoices/PaymentStatusSelect";
import { SortControl, type SortDirection } from "@/components/ui/SortControl";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch, apiFetchBlob, orgPath } from "@/lib/api";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import {
  PAYMENT_STATUSES,
  getPaymentStatusLabel,
  isPaymentStatus,
  type PaymentStatus,
} from "@/lib/payment-status";
import type {
  InvoiceSummary,
  PaginatedInvoices,
  SendInvoiceEmailResponse,
} from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const pageSize = 10;

// Translated at render time, not inside the useCallback below, since
// useTranslation()'s t is not identity-stable (see dashboard/customers/
// settings pages for the same pattern).
const GENERIC_LOAD_ERROR = "__generic_load_error__";

type PaymentStatusFilter = PaymentStatus | "all";
type DateRangePreset = "all" | "today" | "week" | "month" | "year";
type InvoiceSortBy = "invoice_number" | "created_at" | "total" | "customer_name";

const selectClass =
  "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none ring-slate-400 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-50";

const numberInputClass =
  "w-28 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none ring-slate-400 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-50";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Converts a date-range preset into a "created_after" ISO timestamp in the
 * viewer's local time (so "Today"/"This week" match their own calendar day). */
function computeCreatedAfter(preset: DateRangePreset): string | null {
  if (preset === "all") return null;
  const start = new Date();
  if (preset === "today") {
    start.setHours(0, 0, 0, 0);
  } else if (preset === "week") {
    const day = start.getDay();
    const diffToMonday = (day + 6) % 7;
    start.setDate(start.getDate() - diffToMonday);
    start.setHours(0, 0, 0, 0);
  } else if (preset === "month") {
    start.setDate(1);
    start.setHours(0, 0, 0, 0);
  } else if (preset === "year") {
    start.setMonth(0, 1);
    start.setHours(0, 0, 0, 0);
  }
  return start.toISOString();
}

export default function InvoicesPage() {
  const toast = useToast();
  const { t } = useTranslation();
  const [data, setData] = useState<PaginatedInvoices | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [sendingId, setSendingId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [paymentStatus, setPaymentStatus] = useState<PaymentStatusFilter>("all");
  const [dateRange, setDateRange] = useState<DateRangePreset>("all");
  const [minTotal, setMinTotal] = useState("");
  const [maxTotal, setMaxTotal] = useState("");
  const [sortBy, setSortBy] = useState<InvoiceSortBy>("created_at");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");

  const sortFields: { value: InvoiceSortBy; label: string }[] = [
    { value: "created_at", label: t("invoices.sortCreatedDate") },
    { value: "invoice_number", label: t("invoices.sortInvoiceNumber") },
    { value: "total", label: t("invoices.sortTotalAmount") },
    { value: "customer_name", label: t("invoices.sortCustomerName") },
  ];

  const hasActiveFilters =
    debouncedSearch.trim() !== "" ||
    paymentStatus !== "all" ||
    dateRange !== "all" ||
    minTotal.trim() !== "" ||
    maxTotal.trim() !== "";
  const isDefaultState =
    !hasActiveFilters && sortBy === "created_at" && sortDir === "desc";

  function resetToFirstPage<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setOffset(0);
    };
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({
        limit: String(pageSize),
        offset: String(offset),
        sort_by: sortBy,
        sort_dir: sortDir,
      });
      if (debouncedSearch.trim()) q.set("search", debouncedSearch.trim());
      if (paymentStatus !== "all") q.set("payment_status", paymentStatus);
      const createdAfter = computeCreatedAfter(dateRange);
      if (createdAfter) q.set("created_after", createdAfter);
      if (minTotal.trim()) q.set("min_total", minTotal.trim());
      if (maxTotal.trim()) q.set("max_total", maxTotal.trim());

      const json = await apiFetch<PaginatedInvoices>(
        `${orgPath("invoices")}?${q.toString()}`
      );
      setData(json);
    } catch (e) {
      setData(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, [
    offset,
    debouncedSearch,
    paymentStatus,
    dateRange,
    minTotal,
    maxTotal,
    sortBy,
    sortDir,
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  function resetFilters() {
    setSearch("");
    setPaymentStatus("all");
    setDateRange("all");
    setMinTotal("");
    setMaxTotal("");
    setSortBy("created_at");
    setSortDir("desc");
    setOffset(0);
  }

  function updateInvoiceStatus(invoiceId: string, payment_status: PaymentStatus) {
    setData((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        items: prev.items.map((row) =>
          row.id === invoiceId ? { ...row, payment_status } : row
        ),
      };
    });
  }

  async function downloadInvoicePdf(invoiceId: string, invoiceNumber: string) {
    if (downloadingId) return;
    setDownloadingId(invoiceId);
    const loadingId = toast.loading(t("invoices.toastPreparingPdf"));
    try {
      const blob = await apiFetchBlob(orgPath(`invoices/${invoiceId}/pdf`));
      downloadBlob(blob, `${invoiceNumber}.pdf`);
      toast.dismiss(loadingId);
      toast.success(t("invoices.toastPdfDownloaded"));
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("invoices.toastPdfError")));
    } finally {
      setDownloadingId(null);
    }
  }

  async function sendInvoiceEmail(invoiceId: string, invoiceNumber: string) {
    if (sendingId) return;
    setSendingId(invoiceId);
    const loadingId = toast.loading(t("invoices.toastSendingEmail"));
    try {
      const result = await apiFetch<SendInvoiceEmailResponse>(
        orgPath(`invoices/${invoiceId}/send-email`),
        { method: "POST" }
      );
      toast.dismiss(loadingId);
      toast.success(
        t("invoices.toastEmailSent", { number: invoiceNumber, email: result.sent_to })
      );
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : formatApiError(err, t("invoices.toastEmailError"))
      );
    } finally {
      setSendingId(null);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !loading && data !== null && data.items.length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {t("invoices.title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{t("invoices.subtitle")}</p>
        </div>
        <Link
          href="/invoices/new"
          className="inline-flex shrink-0 items-center justify-center rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:mt-0"
        >
          {t("invoices.newInvoice")}
        </Link>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <div className="space-y-4">
          <div>
            <label htmlFor="invoice-search" className="sr-only">
              {t("invoices.searchAriaLabel")}
            </label>
            <input
              id="invoice-search"
              type="search"
              value={search}
              onChange={(e) => resetToFirstPage(setSearch)(e.target.value)}
              placeholder={t("invoices.searchPlaceholder")}
              className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <select
              value={paymentStatus}
              onChange={(e) =>
                resetToFirstPage(setPaymentStatus)(
                  e.target.value as PaymentStatusFilter
                )
              }
              className={selectClass}
              aria-label={t("invoices.filterStatusAriaLabel")}
            >
              <option value="all">{t("invoices.allStatuses")}</option>
              {PAYMENT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {getPaymentStatusLabel(t, status)}
                </option>
              ))}
            </select>

            <select
              value={dateRange}
              onChange={(e) =>
                resetToFirstPage(setDateRange)(e.target.value as DateRangePreset)
              }
              className={selectClass}
              aria-label={t("invoices.filterDateAriaLabel")}
            >
              <option value="all">{t("invoices.dateAll")}</option>
              <option value="today">{t("invoices.dateToday")}</option>
              <option value="week">{t("invoices.dateWeek")}</option>
              <option value="month">{t("invoices.dateMonth")}</option>
              <option value="year">{t("invoices.dateYear")}</option>
            </select>

            <input
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={minTotal}
              onChange={(e) => resetToFirstPage(setMinTotal)(e.target.value)}
              placeholder={t("invoices.minTotalPlaceholder")}
              aria-label={t("invoices.minTotalAriaLabel")}
              className={numberInputClass}
            />
            <input
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={maxTotal}
              onChange={(e) => resetToFirstPage(setMaxTotal)(e.target.value)}
              placeholder={t("invoices.maxTotalPlaceholder")}
              aria-label={t("invoices.maxTotalAriaLabel")}
              className={numberInputClass}
            />

            <SortControl
              fields={sortFields}
              sortBy={sortBy}
              sortDir={sortDir}
              onSortByChange={resetToFirstPage((v: string) =>
                setSortBy(v as InvoiceSortBy)
              )}
              onSortDirChange={resetToFirstPage(setSortDir)}
            />

            <button
              type="button"
              onClick={resetFilters}
              disabled={isDefaultState}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("invoices.resetFilters")}
            </button>
          </div>
        </div>
      </section>

      {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error === GENERIC_LOAD_ERROR ? t("invoices.loadError") : error}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-4 py-3 sm:px-6">{t("invoices.colInvoice")}</th>
                <th className="hidden px-4 py-3 sm:table-cell sm:px-6">
                  {t("invoices.colCustomer")}
                </th>
                <th className="px-4 py-3 sm:px-6">{t("invoices.colStatus")}</th>
                <th className="px-4 py-3 sm:px-6">{t("invoices.colSubtotal")}</th>
                <th className="hidden px-4 py-3 md:table-cell md:px-6">
                  {t("invoices.colTax")}
                </th>
                <th className="px-4 py-3 sm:px-6">{t("invoices.colTotal")}</th>
                <th className="hidden px-4 py-3 lg:table-cell lg:px-6">
                  {t("invoices.colCreated")}
                </th>
                <th className="px-4 py-3 sm:px-6">
                  <span className="sr-only">{t("invoices.colActions")}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-8 text-center text-slate-500 sm:px-6"
                  >
                    {t("invoices.loading")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-8 text-center text-slate-500 sm:px-6"
                  >
                    {hasActiveFilters ? (
                      <div className="space-y-2">
                        <p>{t("invoices.noMatch")}</p>
                        <button
                          type="button"
                          onClick={resetFilters}
                          className="font-medium text-slate-700 underline hover:text-slate-900"
                        >
                          {t("invoices.resetFilters")}
                        </button>
                      </div>
                    ) : (
                      t("invoices.noneYet")
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((row) => {
                  const status = isPaymentStatus(row.payment_status)
                    ? row.payment_status
                    : "pending";

                  return (
                    <tr key={row.id} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3 font-mono text-xs text-slate-900 sm:px-6">
                        {row.invoice_number}
                      </td>
                      <td className="hidden px-4 py-3 text-slate-600 sm:table-cell sm:px-6">
                        {row.customer_name ?? (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 sm:px-6">
                        <PaymentStatusSelect
                          invoiceId={row.id}
                          value={status}
                          onUpdated={(next) =>
                            updateInvoiceStatus(row.id, next)
                          }
                        />
                      </td>
                      <td className="px-4 py-3 text-slate-800 sm:px-6">
                        {formatCurrency(row.subtotal, row.currency_code)}
                      </td>
                      <td className="hidden px-4 py-3 text-slate-800 md:table-cell md:px-6">
                        {formatCurrency(row.tax_amount, row.currency_code)}
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-900 sm:px-6">
                        {formatCurrency(row.total, row.currency_code)}
                      </td>
                      <td className="hidden px-4 py-3 text-slate-600 lg:table-cell lg:px-6">
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 sm:px-6">
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              void downloadInvoicePdf(row.id, row.invoice_number)
                            }
                            disabled={
                              downloadingId === row.id || sendingId === row.id
                            }
                            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {downloadingId === row.id
                              ? t("invoices.preparing")
                              : t("invoices.downloadPdf")}
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              void sendInvoiceEmail(row.id, row.invoice_number)
                            }
                            disabled={
                              sendingId === row.id || downloadingId === row.id
                            }
                            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {sendingId === row.id
                              ? t("invoices.sending")
                              : t("invoices.sendEmail")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        {data && data.total > pageSize ? (
          <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span>
              {t("invoices.pagination", {
                page: currentPage,
                totalPages,
                total: data.total,
              })}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0 || loading}
                onClick={() => setOffset((o) => Math.max(0, o - pageSize))}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("invoices.previous")}
              </button>
              <button
                type="button"
                disabled={offset + pageSize >= data.total || loading}
                onClick={() => setOffset((o) => o + pageSize)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("invoices.next")}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
