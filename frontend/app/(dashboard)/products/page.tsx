"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ProductForm } from "@/components/products/ProductForm";
import {
  RowActionsMenu,
  STICKY_ACTIONS_TD_CLASS,
  STICKY_ACTIONS_TH_CLASS,
} from "@/components/ui/RowActionsMenu";
import { SortControl, type SortDirection } from "@/components/ui/SortControl";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch, apiFetchBlob, orgPath } from "@/lib/api";
import { formatApiError, isEmailNotVerifiedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import {
  PRODUCT_TYPES,
  PRODUCT_TYPE_BADGE_CLASS,
  getProductTypeLabel,
  isProductType,
  type ProductType,
} from "@/lib/product-type";
import type { PaginatedProducts, Product } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const pageSize = 10;

const GENERIC_LOAD_ERROR = "__generic_load_error__";

type ProductTypeFilter = ProductType | "all";
type ActiveFilter = "active" | "archived" | "all";
type ProductSortBy = "created_at" | "name" | "default_unit_price";

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

export default function ProductsPage() {
  const { t } = useTranslation();
  const toast = useToast();

  const [data, setData] = useState<PaginatedProducts | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [archivingId, setArchivingId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [typeFilter, setTypeFilter] = useState<ProductTypeFilter>("all");
  // Defaults to "active" -- archived products are hidden from the catalog
  // view by default (see the plan's "archived, hidden by default" rule),
  // not physically removed.
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("active");
  const [sortBy, setSortBy] = useState<ProductSortBy>("created_at");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");

  const sortFields: { value: ProductSortBy; label: string }[] = [
    { value: "created_at", label: t("invoices.sortCreatedDate") },
    { value: "name", label: t("common.name") },
    { value: "default_unit_price", label: t("products.defaultPriceLabel") },
  ];

  const hasActiveFilters =
    debouncedSearch.trim() !== "" || typeFilter !== "all" || activeFilter !== "active";
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
      if (typeFilter !== "all") q.set("type", typeFilter);
      if (activeFilter !== "all") q.set("active", activeFilter === "active" ? "true" : "false");

      const json = await apiFetch<PaginatedProducts>(`${orgPath("products")}?${q.toString()}`, {
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
  }, [offset, debouncedSearch, typeFilter, activeFilter, sortBy, sortDir]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  function resetFilters() {
    setSearch("");
    setTypeFilter("all");
    setActiveFilter("active");
    setSortBy("created_at");
    setSortDir("desc");
    setOffset(0);
  }

  async function downloadTemplate(format: "csv" | "xlsx") {
    try {
      const blob = await apiFetchBlob(orgPath(`products/import/template.${format}`));
      downloadBlob(blob, `products-template.${format}`);
    } catch {
      toast.error(t("products.templateDownloadError"));
    }
  }

  async function archiveProduct(product: Product) {
    if (archivingId) return;
    setArchivingId(product.id);
    try {
      await apiFetch<Product>(orgPath(`products/${product.id}/archive`), { method: "POST" });
      toast.success(t("products.toastArchived"));
      await load();
    } catch (err) {
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : formatApiError(err, t("products.toastArchiveError"))
      );
    } finally {
      setArchivingId(null);
    }
  }

  async function restoreProduct(product: Product) {
    if (archivingId) return;
    setArchivingId(product.id);
    try {
      await apiFetch<Product>(orgPath(`products/${product.id}/restore`), { method: "POST" });
      toast.success(t("products.toastRestored"));
      await load();
    } catch (err) {
      toast.error(
        isEmailNotVerifiedError(err)
          ? t("errors.emailNotVerified")
          : formatApiError(err, t("products.toastRestoreError"))
      );
    } finally {
      setArchivingId(null);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !loading && data !== null && data.items.length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {t("products.title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{t("products.subtitle")}</p>
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
            href="/products/import"
            className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
          >
            {t("products.importButton")}
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

      {editingProduct ? (
        <ProductForm
          product={editingProduct}
          onSaved={async () => {
            setEditingProduct(null);
            await load();
          }}
          onCancel={() => setEditingProduct(null)}
        />
      ) : (
        <ProductForm onSaved={() => load()} />
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <div className="space-y-4">
          <div>
            <label htmlFor="product-search" className="sr-only">
              {t("products.searchAriaLabel")}
            </label>
            <input
              id="product-search"
              type="search"
              value={search}
              onChange={(e) => resetToFirstPage(setSearch)(e.target.value)}
              placeholder={t("products.searchPlaceholder")}
              className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none ring-slate-400 focus:ring-2"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <select
              value={typeFilter}
              onChange={(e) =>
                resetToFirstPage(setTypeFilter)(e.target.value as ProductTypeFilter)
              }
              className={selectClass}
              aria-label={t("products.filterTypeAriaLabel")}
            >
              <option value="all">{t("products.allTypes")}</option>
              {PRODUCT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {getProductTypeLabel(t, type)}
                </option>
              ))}
            </select>

            <select
              value={activeFilter}
              onChange={(e) =>
                resetToFirstPage(setActiveFilter)(e.target.value as ActiveFilter)
              }
              className={selectClass}
              aria-label={t("products.filterActiveAriaLabel")}
            >
              <option value="active">{t("products.filterActiveOnly")}</option>
              <option value="archived">{t("products.filterArchivedOnly")}</option>
              <option value="all">{t("products.filterAll")}</option>
            </select>

            <SortControl
              fields={sortFields}
              sortBy={sortBy}
              sortDir={sortDir}
              onSortByChange={resetToFirstPage((v: string) => setSortBy(v as ProductSortBy))}
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
          {error === GENERIC_LOAD_ERROR ? t("products.loadError") : error}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-4 py-3 sm:px-6">{t("common.name")}</th>
                <th className="px-4 py-3 sm:px-6">{t("products.typeLabel")}</th>
                <th className="hidden px-4 py-3 md:table-cell md:px-6">
                  {t("products.skuLabel")}
                </th>
                <th className="px-4 py-3 sm:px-6">{t("products.defaultPriceLabel")}</th>
                <th className="hidden px-4 py-3 lg:table-cell lg:px-6">
                  {t("products.statusLabel")}
                </th>
                <th className={STICKY_ACTIONS_TH_CLASS}>
                  <span className="sr-only">{t("invoices.colActions")}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-500 sm:px-6">
                    {t("products.loading")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-500 sm:px-6">
                    {hasActiveFilters ? (
                      <div className="space-y-2">
                        <p>{t("products.noMatch")}</p>
                        <button
                          type="button"
                          onClick={resetFilters}
                          className="font-medium text-slate-700 underline hover:text-slate-900"
                        >
                          {t("invoices.resetFilters")}
                        </button>
                      </div>
                    ) : (
                      t("products.noneYet")
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((product) => {
                  const type = isProductType(product.type) ? product.type : "product";
                  return (
                    <tr key={product.id} className="group hover:bg-slate-50/80">
                      <td className="px-4 py-3 font-medium text-slate-900 sm:px-6">
                        {product.name}
                        {product.description ? (
                          <p className="mt-0.5 max-w-xs truncate text-xs font-normal text-slate-500">
                            {product.description}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 sm:px-6">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${PRODUCT_TYPE_BADGE_CLASS[type]}`}
                        >
                          {getProductTypeLabel(t, type)}
                        </span>
                      </td>
                      <td className="hidden px-4 py-3 text-slate-600 md:table-cell md:px-6">
                        {product.sku || "—"}
                      </td>
                      <td className="px-4 py-3 text-slate-800 sm:px-6">
                        {formatCurrency(product.default_unit_price, product.currency_code)}
                      </td>
                      <td className="hidden px-4 py-3 lg:table-cell lg:px-6">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${
                            product.active
                              ? "bg-emerald-100 text-emerald-900 ring-emerald-200/80"
                              : "bg-slate-100 text-slate-600 ring-slate-200/80"
                          }`}
                        >
                          {product.active ? t("products.statusActive") : t("products.statusArchived")}
                        </span>
                      </td>
                      <td className={STICKY_ACTIONS_TD_CLASS}>
                        <RowActionsMenu label={t("common.moreActions")}>
                          <RowActionsMenu.Item onSelect={() => setEditingProduct(product)}>
                            {t("common.edit")}
                          </RowActionsMenu.Item>
                          {product.active ? (
                            <RowActionsMenu.Item
                              destructive
                              disabled={archivingId === product.id}
                              onSelect={() => void archiveProduct(product)}
                            >
                              {t("products.archiveButton")}
                            </RowActionsMenu.Item>
                          ) : (
                            <RowActionsMenu.Item
                              disabled={archivingId === product.id}
                              onSelect={() => void restoreProduct(product)}
                            >
                              {t("products.restoreButton")}
                            </RowActionsMenu.Item>
                          )}
                        </RowActionsMenu>
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
