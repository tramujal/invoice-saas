"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AddCustomerForm } from "@/components/customers/AddCustomerForm";
import { useToast } from "@/components/ui/toast";
import { SortControl, type SortDirection } from "@/components/ui/SortControl";
import { ApiError, apiFetchBlob, apiFetch, orgPath } from "@/lib/api";
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
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-6 py-12 text-center sm:px-10">
        <h2 className="text-lg font-semibold text-slate-900">
          {t("customers.emptyFilteredTitle")}
        </h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
          {t("customers.emptyFilteredDescription")}
        </p>
        <button
          type="button"
          onClick={onReset}
          className="mt-4 font-medium text-slate-700 underline hover:text-slate-900"
        >
          {t("invoices.resetFilters")}
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-6 py-12 text-center sm:px-10">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-200/80 text-slate-600">
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
      </div>
      <h2 className="mt-4 text-lg font-semibold text-slate-900">
        {t("customers.emptyTitle")}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
        {t("customers.emptyDescription")}
      </p>
    </div>
  );
}

export default function CustomersPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [items, setItems] = useState<Customer[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = Boolean(opts?.silent);
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const q = new URLSearchParams({ sort_by: sortBy, sort_dir: sortDir });
      if (debouncedSearch.trim()) q.set("search", debouncedSearch.trim());
      const json = await apiFetch<Customer[]>(
        `${orgPath("customers")}?${q.toString()}`
      );
      setItems(json);
      if (!silent) setError(null);
    } catch (e) {
      if (!silent) {
        setItems(null);
        setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [debouncedSearch, sortBy, sortDir]);

  useEffect(() => {
    void load();
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

  const showEmpty = !loading && items !== null && items.length === 0;
  const showTable = !loading && items !== null && items.length > 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {t("customers.title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{t("customers.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
          <button
            type="button"
            onClick={() => void downloadTemplate("csv")}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
          >
            {t("customers.downloadCsvTemplate")}
          </button>
          <button
            type="button"
            onClick={() => void downloadTemplate("xlsx")}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
          >
            {t("customers.downloadXlsxTemplate")}
          </button>
          <Link
            href="/customers/import"
            className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
          >
            {t("customers.importButton")}
          </Link>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? t("common.refreshing") : t("common.refresh")}
          </button>
        </div>
      </header>

      <AddCustomerForm onCreated={() => load({ silent: true })} />

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="sm:max-w-sm sm:flex-1">
            <label htmlFor="customer-search" className="sr-only">
              {t("customers.searchAriaLabel")}
            </label>
            <input
              id="customer-search"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("customers.searchPlaceholder")}
              className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <SortControl
              fields={sortFields}
              sortBy={sortBy}
              sortDir={sortDir}
              onSortByChange={(v) => setSortBy(v as CustomerSortBy)}
              onSortDirChange={setSortDir}
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
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-4 py-3 sm:px-6">{t("common.name")}</th>
                  <th className="px-4 py-3 sm:px-6">{t("common.email")}</th>
                  <th className="hidden px-4 py-3 md:table-cell md:px-6">
                    {t("common.phone")}
                  </th>
                  <th className="hidden px-4 py-3 lg:table-cell lg:px-6">
                    {t("common.address")}
                  </th>
                  <th className="hidden px-4 py-3 lg:table-cell lg:px-6">
                    {t("customers.taxIdColumn")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items!.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50/80">
                    <td className="px-4 py-3 font-medium text-slate-900 sm:px-6">
                      {c.name}
                    </td>
                    <td className="px-4 py-3 text-slate-700 sm:px-6">{c.email}</td>
                    <td className="hidden px-4 py-3 text-slate-600 md:table-cell md:px-6">
                      {c.phone || "—"}
                    </td>
                    <td className="hidden max-w-xs truncate px-4 py-3 text-slate-600 lg:table-cell lg:px-6">
                      {c.address || "—"}
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 lg:table-cell lg:px-6">
                      {c.tax_id || "—"}
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
