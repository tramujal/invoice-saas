"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import {
  RowActionsMenu,
  STICKY_ACTIONS_TD_CLASS,
  STICKY_ACTIONS_TH_CLASS,
} from "@/components/ui/RowActionsMenu";
import { SortControl, type SortDirection } from "@/components/ui/SortControl";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch, apiFetchBlob, orgPath } from "@/lib/api";
import {
  formatApiError,
  isEmailNotVerifiedError,
  isRateLimitedError,
} from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import {
  QUOTE_STATUSES,
  QUOTE_STATUS_BADGE_CLASS,
  getQuoteStatusLabel,
  isQuoteStatus,
  type QuoteStatus,
} from "@/lib/quote-status";
import type {
  ConvertQuoteToInvoiceResponse,
  PaginatedQuotes,
  QuoteSummary,
  SendQuoteEmailResponse,
} from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const pageSize = 10;

const GENERIC_LOAD_ERROR = "__generic_load_error__";

type StatusFilter = QuoteStatus | "all";
type ActiveFilter = "active" | "archived" | "all";
type QuoteSortBy = "created_at" | "quote_number" | "total" | "customer_name" | "expiry_date";

const selectClass =
  "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none ring-slate-400 focus:ring-2 disabled:cursor-not-allowed disabled:bg-slate-50";

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

function QuoteStatusBadge({ status, t }: { status: QuoteStatus; t: ReturnType<typeof useTranslation>["t"] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${QUOTE_STATUS_BADGE_CLASS[status]}`}
    >
      {getQuoteStatusLabel(t, status)}
    </span>
  );
}

function QuotesContent() {
  const toast = useToast();
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [data, setData] = useState<PaginatedQuotes | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("active");
  const [sortBy, setSortBy] = useState<QuoteSortBy>("created_at");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");

  const sortFields: { value: QuoteSortBy; label: string }[] = [
    { value: "created_at", label: t("quotes.sortCreatedDate") },
    { value: "quote_number", label: t("quotes.sortQuoteNumber") },
    { value: "total", label: t("quotes.sortTotalAmount") },
    { value: "customer_name", label: t("quotes.sortCustomerName") },
    { value: "expiry_date", label: t("quotes.sortExpiryDate") },
  ];

  const hasActiveFilters =
    debouncedSearch.trim() !== "" || status !== "all" || activeFilter !== "active";
  const isDefaultState =
    !hasActiveFilters && sortBy === "created_at" && sortDir === "desc";

  function resetToFirstPage<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setOffset(0);
    };
  }

  // Aborts any still-in-flight previous load() (e.g. a fast-typing
  // debounced search superseding an earlier request) so a slow stale
  // response can never overwrite a newer one, and so navigating away
  // mid-request actually cancels it instead of abandoning it.
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
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
      if (status !== "all") q.set("status", status);
      if (activeFilter !== "all") q.set("active", activeFilter === "active" ? "true" : "false");

      const json = await apiFetch<PaginatedQuotes>(`${orgPath("quotes")}?${q.toString()}`, {
        signal: controller.signal,
      });
      setData(json);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      // Only the still-current (non-superseded) call may clear the
      // loading flag -- otherwise an aborted call's finally could turn
      // off the spinner for a newer request that's still in flight.
      if (abortRef.current === controller) setLoading(false);
    }
  }, [offset, debouncedSearch, status, activeFilter, sortBy, sortDir]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  // A dashboard insight's "View pending/expiring quotes" CTA links here
  // with ?status=sent prefilled -- same one-shot-then-strip convention as
  // invoices/page.tsx's own ?status= handling.
  useEffect(() => {
    const statusParam = searchParams.get("status");
    if (statusParam && isQuoteStatus(statusParam)) {
      resetToFirstPage(setStatus)(statusParam);
      router.replace("/quotes");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function resetFilters() {
    setSearch("");
    setStatus("all");
    setActiveFilter("active");
    setSortBy("created_at");
    setSortDir("desc");
    setOffset(0);
  }

  async function downloadQuotePdf(quoteId: string, quoteNumber: string) {
    if (busyId) return;
    setBusyId(quoteId);
    const loadingId = toast.loading(t("quotes.toastPreparingPdf"));
    try {
      const blob = await apiFetchBlob(orgPath(`quotes/${quoteId}/pdf`));
      downloadBlob(blob, `${quoteNumber}.pdf`);
      toast.dismiss(loadingId);
      toast.success(t("quotes.toastPdfDownloaded"));
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("quotes.toastPdfError")));
    } finally {
      setBusyId(null);
    }
  }

  async function sendQuoteEmail(quoteId: string, quoteNumber: string) {
    if (busyId) return;
    setBusyId(quoteId);
    const loadingId = toast.loading(t("quotes.toastSendingEmail"));
    try {
      const result = await apiFetch<SendQuoteEmailResponse>(orgPath(`quotes/${quoteId}/send-email`), {
        method: "POST",
      });
      toast.dismiss(loadingId);
      toast.success(t("quotes.toastEmailSent", { number: quoteNumber, email: result.sent_to }));
      void load();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : isRateLimitedError(err)
            ? t("errors.rateLimitedInvoiceEmail")
            : formatApiError(err, t("quotes.toastEmailError"))
      );
    } finally {
      setBusyId(null);
    }
  }

  async function markQuote(quoteId: string, action: "mark-accepted" | "mark-rejected") {
    if (busyId) return;
    setBusyId(quoteId);
    try {
      await apiFetch(orgPath(`quotes/${quoteId}/${action}`), { method: "POST" });
      toast.success(
        action === "mark-accepted" ? t("quotes.toastMarkedAccepted") : t("quotes.toastMarkedRejected")
      );
      void load();
    } catch (err) {
      toast.error(formatApiError(err, t("quotes.toastMarkError")));
    } finally {
      setBusyId(null);
    }
  }

  async function convertQuote(quoteId: string) {
    if (busyId) return;
    setBusyId(quoteId);
    const loadingId = toast.loading(t("quotes.toastConverting"));
    try {
      const result = await apiFetch<ConvertQuoteToInvoiceResponse>(orgPath(`quotes/${quoteId}/convert`), {
        method: "POST",
      });
      toast.dismiss(loadingId);
      toast.success(t("quotes.toastConverted", { number: result.invoice_number }));
      void load();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("quotes.toastConvertError")));
    } finally {
      setBusyId(null);
    }
  }

  async function duplicateQuote(quoteId: string) {
    if (busyId) return;
    setBusyId(quoteId);
    const loadingId = toast.loading(t("quotes.toastDuplicating"));
    try {
      await apiFetch(orgPath(`quotes/${quoteId}/duplicate`), { method: "POST" });
      toast.dismiss(loadingId);
      toast.success(t("quotes.toastDuplicated"));
      void load();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("quotes.toastDuplicateError")));
    } finally {
      setBusyId(null);
    }
  }

  async function archiveOrRestore(quoteId: string, archive: boolean) {
    if (busyId) return;
    setBusyId(quoteId);
    try {
      await apiFetch(orgPath(`quotes/${quoteId}/${archive ? "archive" : "restore"}`), {
        method: "POST",
      });
      toast.success(archive ? t("quotes.toastArchived") : t("quotes.toastRestored"));
      void load();
    } catch (err) {
      toast.error(
        formatApiError(err, archive ? t("quotes.toastArchiveError") : t("quotes.toastRestoreError"))
      );
    } finally {
      setBusyId(null);
    }
  }

  async function deleteDraft(quoteId: string) {
    if (busyId) return;
    if (!window.confirm(t("quotes.deleteConfirm"))) return;
    setBusyId(quoteId);
    try {
      await apiFetch(orgPath(`quotes/${quoteId}`), { method: "DELETE", parseJson: false });
      toast.success(t("quotes.toastDeleted"));
      void load();
    } catch (err) {
      toast.error(formatApiError(err, t("quotes.toastDeleteError")));
    } finally {
      setBusyId(null);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !loading && data !== null && data.items.length === 0;

  function actionsFor(row: QuoteSummary) {
    const busy = busyId === row.id;
    const items: React.ReactNode[] = [];
    items.push(
      <RowActionsMenu.Item
        key="pdf"
        onSelect={() => void downloadQuotePdf(row.id, row.quote_number)}
        disabled={busy}
      >
        {t("quotes.downloadPdf")}
      </RowActionsMenu.Item>
    );

    if (row.effective_status === "draft" || row.effective_status === "sent") {
      items.push(
        <RowActionsMenu.LinkItem key="edit" href={`/quotes/${row.id}/edit`}>
          {t("quotes.edit")}
        </RowActionsMenu.LinkItem>
      );
      items.push(
        <RowActionsMenu.Item
          key="send"
          onSelect={() => void sendQuoteEmail(row.id, row.quote_number)}
          disabled={busy || row.customer_id === null}
        >
          {t("quotes.sendEmail")}
        </RowActionsMenu.Item>
      );
    }

    if (row.effective_status === "sent") {
      items.push(
        <RowActionsMenu.Item
          key="accept"
          onSelect={() => void markQuote(row.id, "mark-accepted")}
          disabled={busy}
        >
          {t("quotes.markAccepted")}
        </RowActionsMenu.Item>
      );
      items.push(
        <RowActionsMenu.Item
          key="reject"
          onSelect={() => void markQuote(row.id, "mark-rejected")}
          disabled={busy}
        >
          {t("quotes.markRejected")}
        </RowActionsMenu.Item>
      );
    }

    if (row.status === "accepted") {
      items.push(
        <RowActionsMenu.Item key="convert" onSelect={() => void convertQuote(row.id)} disabled={busy}>
          {t("quotes.convert")}
        </RowActionsMenu.Item>
      );
    }

    items.push(
      <RowActionsMenu.Item key="duplicate" onSelect={() => void duplicateQuote(row.id)} disabled={busy}>
        {t("quotes.duplicate")}
      </RowActionsMenu.Item>
    );

    if (row.active) {
      items.push(
        <RowActionsMenu.Item
          key="archive"
          onSelect={() => void archiveOrRestore(row.id, true)}
          disabled={busy}
        >
          {t("quotes.archive")}
        </RowActionsMenu.Item>
      );
    } else {
      items.push(
        <RowActionsMenu.Item
          key="restore"
          onSelect={() => void archiveOrRestore(row.id, false)}
          disabled={busy}
        >
          {t("quotes.restore")}
        </RowActionsMenu.Item>
      );
    }

    if (row.status === "draft") {
      items.push(
        <RowActionsMenu.Item
          key="delete"
          destructive
          onSelect={() => void deleteDraft(row.id)}
          disabled={busy}
        >
          {t("quotes.delete")}
        </RowActionsMenu.Item>
      );
    }

    return items;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{t("quotes.title")}</h1>
          <p className="mt-1 text-sm text-slate-500">{t("quotes.subtitle")}</p>
        </div>
        <Link
          href="/quotes/new"
          className="inline-flex shrink-0 items-center justify-center rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:mt-0"
        >
          {t("quotes.newQuote")}
        </Link>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <div className="space-y-4">
          <div>
            <label htmlFor="quote-search" className="sr-only">
              {t("quotes.searchAriaLabel")}
            </label>
            <input
              id="quote-search"
              type="search"
              value={search}
              onChange={(e) => resetToFirstPage(setSearch)(e.target.value)}
              placeholder={t("quotes.searchPlaceholder")}
              className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <select
              value={status}
              onChange={(e) => resetToFirstPage(setStatus)(e.target.value as StatusFilter)}
              className={selectClass}
              aria-label={t("quotes.filterStatusAriaLabel")}
            >
              <option value="all">{t("quotes.allStatuses")}</option>
              {QUOTE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {getQuoteStatusLabel(t, s)}
                </option>
              ))}
            </select>

            <select
              value={activeFilter}
              onChange={(e) => resetToFirstPage(setActiveFilter)(e.target.value as ActiveFilter)}
              className={selectClass}
              aria-label={t("quotes.filterActiveAriaLabel")}
            >
              <option value="active">{t("quotes.showActive")}</option>
              <option value="archived">{t("quotes.showArchived")}</option>
              <option value="all">{t("quotes.showAll")}</option>
            </select>

            <SortControl
              fields={sortFields}
              sortBy={sortBy}
              sortDir={sortDir}
              onSortByChange={resetToFirstPage((v: string) => setSortBy(v as QuoteSortBy))}
              onSortDirChange={resetToFirstPage(setSortDir)}
            />

            <button
              type="button"
              onClick={resetFilters}
              disabled={isDefaultState}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("quotes.resetFilters")}
            </button>
          </div>
        </div>
      </section>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("quotes.loadError") : error}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-4 py-3 sm:px-6">{t("quotes.colQuote")}</th>
                <th className="hidden px-4 py-3 sm:table-cell sm:px-6">{t("quotes.colCustomer")}</th>
                <th className="px-4 py-3 sm:px-6">{t("quotes.colStatus")}</th>
                <th className="px-4 py-3 sm:px-6">{t("quotes.colTotal")}</th>
                <th className="hidden px-4 py-3 lg:table-cell lg:px-6">{t("quotes.colExpiry")}</th>
                <th className="hidden px-4 py-3 lg:table-cell lg:px-6">{t("quotes.colCreated")}</th>
                <th className={STICKY_ACTIONS_TH_CLASS}>
                  <span className="sr-only">{t("quotes.colActions")}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500 sm:px-6">
                    {t("quotes.loading")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500 sm:px-6">
                    {hasActiveFilters ? (
                      <div className="space-y-2">
                        <p>{t("quotes.noMatch")}</p>
                        <button
                          type="button"
                          onClick={resetFilters}
                          className="font-medium text-slate-700 underline hover:text-slate-900"
                        >
                          {t("quotes.resetFilters")}
                        </button>
                      </div>
                    ) : (
                      t("quotes.noneYet")
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((row) => (
                  <tr key={row.id} className="group hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-mono text-xs text-slate-900 sm:px-6">{row.quote_number}</td>
                    <td
                      className="hidden max-w-[180px] truncate px-4 py-3 text-slate-600 sm:table-cell sm:px-6"
                      title={row.customer_name ?? undefined}
                    >
                      {row.customer_name ?? <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-4 py-3 sm:px-6">
                      <QuoteStatusBadge status={row.effective_status} t={t} />
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-900 sm:px-6">
                      {formatCurrency(row.total, row.currency_code)}
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 lg:table-cell lg:px-6">
                      {row.expiry_date ?? <span className="text-slate-400">—</span>}
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 lg:table-cell lg:px-6">
                      {new Date(row.created_at).toLocaleDateString()}
                    </td>
                    <td className={STICKY_ACTIONS_TD_CLASS}>
                      <RowActionsMenu label={t("common.moreActions")}>{actionsFor(row)}</RowActionsMenu>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {data && data.total > pageSize ? (
          <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span>{t("quotes.pagination", { page: currentPage, totalPages, total: data.total })}</span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0 || loading}
                onClick={() => setOffset((o) => Math.max(0, o - pageSize))}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("quotes.previous")}
              </button>
              <button
                type="button"
                disabled={offset + pageSize >= data.total || loading}
                onClick={() => setOffset((o) => o + pageSize)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("quotes.next")}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function QuotesPage() {
  return (
    <Suspense fallback={null}>
      <QuotesContent />
    </Suspense>
  );
}
