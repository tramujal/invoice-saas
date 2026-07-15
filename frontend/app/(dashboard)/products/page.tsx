"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ProductForm } from "@/components/products/ProductForm";
import { Badge } from "@/components/ui/Badge";
import { Button, ButtonLink } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { type ActiveFilterChip, FilterToolbar } from "@/components/ui/FilterToolbar";
import { Select } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
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

  const activeFilterLabels: Record<ActiveFilter, string> = {
    active: t("products.filterActiveOnly"),
    archived: t("products.filterArchivedOnly"),
    all: t("products.filterAll"),
  };

  const filterChips: ActiveFilterChip[] = [];
  if (typeFilter !== "all") {
    const label = `${t("products.typeLabel")}: ${getProductTypeLabel(t, typeFilter)}`;
    filterChips.push({
      key: "type",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setTypeFilter)("all"),
    });
  }
  if (activeFilter !== "active") {
    const label = `${t("products.statusLabel")}: ${activeFilterLabels[activeFilter]}`;
    filterChips.push({
      key: "active",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setActiveFilter)("active"),
    });
  }

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
      <PageHeader
        title={t("products.title")}
        subtitle={t("products.subtitle")}
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
            <path d="M20.91 8.84 8.56 21.19a2 2 0 0 1-2.83 0L2.81 18.27a2 2 0 0 1 0-2.83L15.16 2.91A2 2 0 0 1 16.57 2.3H20a2 2 0 0 1 2 2v3.43a2 2 0 0 1-.59 1.41Z" />
            <path d="M17.5 6.5h.01" />
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
            <ButtonLink href="/products/import" size="sm">
              {t("products.importButton")}
            </ButtonLink>
            <Button type="button" variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
              {loading ? t("common.refreshing") : t("common.refresh")}
            </Button>
          </div>
        }
      />

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

      <FilterToolbar
        searchValue={search}
        onSearchChange={resetToFirstPage(setSearch)}
        searchPlaceholder={t("products.searchPlaceholder")}
        searchAriaLabel={t("products.searchAriaLabel")}
        onReset={resetFilters}
        resetLabel={t("invoices.resetFilters")}
        isDefaultState={isDefaultState}
        filtersLabel={t("common.filters")}
        chips={filterChips}
      >
        <Select
          value={typeFilter}
          onChange={(e) => resetToFirstPage(setTypeFilter)(e.target.value as ProductTypeFilter)}
          fullWidth={false}
          aria-label={t("products.filterTypeAriaLabel")}
        >
          <option value="all">{t("products.allTypes")}</option>
          {PRODUCT_TYPES.map((type) => (
            <option key={type} value={type}>
              {getProductTypeLabel(t, type)}
            </option>
          ))}
        </Select>

        <Select
          value={activeFilter}
          onChange={(e) => resetToFirstPage(setActiveFilter)(e.target.value as ActiveFilter)}
          fullWidth={false}
          aria-label={t("products.filterActiveAriaLabel")}
        >
          <option value="active">{t("products.filterActiveOnly")}</option>
          <option value="archived">{t("products.filterArchivedOnly")}</option>
          <option value="all">{t("products.filterAll")}</option>
        </Select>

        <SortControl
          fields={sortFields}
          sortBy={sortBy}
          sortDir={sortDir}
          onSortByChange={resetToFirstPage((v: string) => setSortBy(v as ProductSortBy))}
          onSortDirChange={resetToFirstPage(setSortDir)}
        />
      </FilterToolbar>

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
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-700">
              <tr>
                <th className="px-4 py-2.5 sm:px-6">{t("common.name")}</th>
                <th className="px-4 py-2.5 sm:px-6">{t("products.typeLabel")}</th>
                <th className="hidden px-4 py-2.5 md:table-cell md:px-6">
                  {t("products.skuLabel")}
                </th>
                <th className="px-4 py-2.5 sm:px-6">{t("products.defaultPriceLabel")}</th>
                <th className="hidden px-4 py-2.5 lg:table-cell lg:px-6">
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
                  <td colSpan={6} className="px-4 py-6 sm:px-6">
                    {hasActiveFilters ? (
                      <EmptyState
                        title={t("products.emptyFilteredTitle")}
                        description={t("products.emptyFilteredDescription")}
                        action={
                          <button
                            type="button"
                            onClick={resetFilters}
                            className="font-medium text-slate-700 underline hover:text-slate-900"
                          >
                            {t("invoices.resetFilters")}
                          </button>
                        }
                      />
                    ) : (
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
                            <path d="M20.91 8.84 8.56 21.19a2 2 0 0 1-2.83 0L2.81 18.27a2 2 0 0 1 0-2.83L15.16 2.91A2 2 0 0 1 16.57 2.3H20a2 2 0 0 1 2 2v3.43a2 2 0 0 1-.59 1.41Z" />
                            <path d="M17.5 6.5h.01" />
                          </svg>
                        }
                        title={t("products.emptyTitle")}
                        description={t("products.emptyDescription")}
                      />
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((product) => {
                  const type = isProductType(product.type) ? product.type : "product";
                  return (
                    <tr key={product.id} className="group transition-colors hover:bg-slate-50/80">
                      <td className="px-4 py-2.5 font-medium text-slate-900 sm:px-6">
                        {product.name}
                        {product.description ? (
                          <p className="mt-0.5 max-w-xs truncate text-xs font-normal text-slate-500">
                            {product.description}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-4 py-2.5 sm:px-6">
                        <Badge className={PRODUCT_TYPE_BADGE_CLASS[type]}>
                          {getProductTypeLabel(t, type)}
                        </Badge>
                      </td>
                      <td className="hidden px-4 py-2.5 text-slate-600 md:table-cell md:px-6">
                        {product.sku || "—"}
                      </td>
                      <td className="px-4 py-2.5 text-slate-800 sm:px-6">
                        {formatCurrency(product.default_unit_price, product.currency_code)}
                      </td>
                      <td className="hidden px-4 py-2.5 lg:table-cell lg:px-6">
                        <Badge
                          className={
                            product.active
                              ? "bg-emerald-100 text-emerald-900 ring-emerald-200/80"
                              : "bg-slate-100 text-slate-600 ring-slate-200/80"
                          }
                        >
                          {product.active ? t("products.statusActive") : t("products.statusArchived")}
                        </Badge>
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
