"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CustomerForm } from "@/components/customers/CustomerForm";
import { Button, ButtonLink } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { FilterToolbar } from "@/components/ui/FilterToolbar";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  RowActionsMenu,
  STICKY_ACTIONS_TD_CLASS,
  STICKY_ACTIONS_TH_CLASS,
} from "@/components/ui/RowActionsMenu";
import { useToast } from "@/components/ui/toast";
import { SortControl, type SortDirection } from "@/components/ui/SortControl";
import { ApiError, apiFetchBlob, apiFetch, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Customer } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

type CustomerSortBy = "name" | "email" | "created_at";

// Translated at render time (see GENERIC_LOAD_ERROR note below).
const GENERIC_LOAD_ERROR = "__generic_load_error__";

function CustomersEmptyState({
  hasActiveFilters,
  onReset,
}: {
  hasActiveFilters: boolean;
  onReset: () => void;
}) {
  const { t } = useTranslation();

  if (hasActiveFilters) {
    return (
      <EmptyState
        title={t("customers.emptyFilteredTitle")}
        description={t("customers.emptyFilteredDescription")}
        action={
          <button
            type="button"
            onClick={onReset}
            className="font-medium text-slate-700 underline hover:text-slate-900"
          >
            {t("invoices.resetFilters")}
          </button>
        }
      />
    );
  }

  return (
    <EmptyState
      icon={
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      }
      title={t("customers.emptyTitle")}
      description={t("customers.emptyDescription")}
    />
  );
}

export default function CustomersPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [items, setItems] = useState<Customer[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [sortBy, setSortBy] = useState<CustomerSortBy>("created_at");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");

  const sortFields: { value: CustomerSortBy; label: string }[] = [
    { value: "created_at", label: t("invoices.sortCreatedDate") },
    { value: "name", label: t("common.name") },
    { value: "email", label: t("common.email") },
  ];

  const hasActiveFilters = debouncedSearch.trim() !== "";
  const isDefaultState =
    !hasActiveFilters && sortBy === "created_at" && sortDir === "desc";

  // Aborts any still-in-flight previous load() (e.g. a fast-typing
  // debounced search superseding an earlier request) so a slow stale
  // response can never overwrite a newer one, and so navigating away
  // mid-request actually cancels it instead of abandoning it.
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = Boolean(opts?.silent);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const q = new URLSearchParams({ sort_by: sortBy, sort_dir: sortDir });
      if (debouncedSearch.trim()) q.set("search", debouncedSearch.trim());
      const json = await apiFetch<Customer[]>(
        `${orgPath("customers")}?${q.toString()}`,
        { signal: controller.signal }
      );
      setItems(json);
      if (!silent) setError(null);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      if (!silent) {
        setItems(null);
        setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
      }
    } finally {
      // Only the still-current (non-superseded) call may clear the
      // loading flag -- otherwise an aborted call's finally could turn
      // off the spinner for a newer request that's still in flight.
      if (!silent && abortRef.current === controller) setLoading(false);
    }
  }, [debouncedSearch, sortBy, sortDir]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  function resetFilters() {
    setSearch("");
    setSortBy("created_at");
    setSortDir("desc");
  }

  async function downloadTemplate(format: "csv" | "xlsx") {
    try {
      const blob = await apiFetchBlob(orgPath(`customers/import/template.${format}`));
      downloadBlob(blob, `customers-template.${format}`);
    } catch {
      toast.error(t("customers.templateDownloadError"));
    }
  }

  async function deleteCustomer(customer: Customer) {
    if (deletingId) return;
    if (!window.confirm(t("customers.deleteConfirm", { name: customer.name }))) return;
    setDeletingId(customer.id);
    const loadingId = toast.loading(t("customers.toastDeleting"));
    try {
      await apiFetch(orgPath(`customers/${customer.id}`), {
        method: "DELETE",
        parseJson: false,
      });
      toast.dismiss(loadingId);
      toast.success(t("customers.toastDeleted"));
      if (editingCustomer?.id === customer.id) setEditingCustomer(null);
      await load();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("customers.toastDeleteError")));
    } finally {
      setDeletingId(null);
    }
  }

  const showEmpty = !loading && items !== null && items.length === 0;
  const showTable = !loading && items !== null && items.length > 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        title={t("customers.title")}
        subtitle={t("customers.subtitle")}
        icon={
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={() => void downloadTemplate("csv")}>
              {t("customers.downloadCsvTemplate")}
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={() => void downloadTemplate("xlsx")}>
              {t("customers.downloadXlsxTemplate")}
            </Button>
            <ButtonLink href="/customers/import" size="sm">
              {t("customers.importButton")}
            </ButtonLink>
            <Button type="button" variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
              {loading ? t("common.refreshing") : t("common.refresh")}
            </Button>
          </div>
        }
      />

      {editingCustomer ? (
        <CustomerForm
          customer={editingCustomer}
          onSaved={async () => {
            setEditingCustomer(null);
            await load({ silent: true });
          }}
          onCancel={() => setEditingCustomer(null)}
        />
      ) : (
        <CustomerForm onSaved={() => load({ silent: true })} />
      )}

      <FilterToolbar
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder={t("customers.searchPlaceholder")}
        searchAriaLabel={t("customers.searchAriaLabel")}
        onReset={resetFilters}
        resetLabel={t("invoices.resetFilters")}
        isDefaultState={isDefaultState}
        filtersLabel={t("common.filters")}
      >
        <SortControl
          fields={sortFields}
          sortBy={sortBy}
          sortDir={sortDir}
          onSortByChange={(v) => setSortBy(v as CustomerSortBy)}
          onSortDirChange={setSortDir}
        />
      </FilterToolbar>

      {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error === GENERIC_LOAD_ERROR ? t("customers.loadError") : error}
        </div>
      ) : null}

      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-500 shadow-sm sm:px-6">
          {t("customers.loading")}
        </div>
      ) : null}

      {showEmpty ? (
        <CustomersEmptyState hasActiveFilters={hasActiveFilters} onReset={resetFilters} />
      ) : null}

      {showTable ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-700">
                <tr>
                  <th className="px-4 py-2.5 sm:px-6">{t("common.name")}</th>
                  <th className="px-4 py-2.5 sm:px-6">{t("common.email")}</th>
                  <th className="hidden px-4 py-2.5 md:table-cell md:px-6">
                    {t("common.phone")}
                  </th>
                  <th className="hidden px-4 py-2.5 lg:table-cell lg:px-6">
                    {t("common.address")}
                  </th>
                  <th className="hidden px-4 py-2.5 lg:table-cell lg:px-6">
                    {t("customers.taxIdColumn")}
                  </th>
                  <th className={STICKY_ACTIONS_TH_CLASS}>
                    <span className="sr-only">{t("customers.colActions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items!.map((c) => (
                  <tr key={c.id} className="group transition-colors hover:bg-slate-50/80">
                    <td
                      className="max-w-[200px] truncate px-4 py-2.5 font-medium text-slate-900 sm:px-6"
                      title={c.name}
                    >
                      {c.name}
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-2.5 text-slate-700 sm:px-6" title={c.email}>
                      {c.email}
                    </td>
                    <td className="hidden px-4 py-2.5 text-slate-600 md:table-cell md:px-6">
                      {c.phone || "—"}
                    </td>
                    <td className="hidden max-w-xs truncate px-4 py-2.5 text-slate-600 lg:table-cell lg:px-6">
                      {c.address || "—"}
                    </td>
                    <td className="hidden px-4 py-2.5 text-slate-600 lg:table-cell lg:px-6">
                      {c.tax_id || "—"}
                    </td>
                    <td className={STICKY_ACTIONS_TD_CLASS}>
                      <RowActionsMenu label={t("common.moreActions")}>
                        <RowActionsMenu.Item onSelect={() => setEditingCustomer(c)}>
                          {t("common.edit")}
                        </RowActionsMenu.Item>
                        <RowActionsMenu.Item
                          destructive
                          disabled={deletingId === c.id}
                          onSelect={() => void deleteCustomer(c)}
                        >
                          {t("common.delete")}
                        </RowActionsMenu.Item>
                      </RowActionsMenu>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
