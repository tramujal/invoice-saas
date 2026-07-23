"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  TABLE_BODY_CLASS,
  TABLE_CELL_CLASS,
  TABLE_CLASS,
  TABLE_HEAD_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_WRAPPER_CLASS,
} from "@/components/ui/TableShell";
import { ApiError, apiFetch } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PaginatedPlatformOrganizations } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const GENERIC_LOAD_ERROR = "__generic_load_error__";
const pageSize = 20;

function formatApproxDate(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

export default function PlatformOrganizationsPage() {
  const { t, language } = useTranslation();
  const [data, setData] = useState<PaginatedPlatformOrganizations | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
      if (debouncedSearch.trim()) q.set("search", debouncedSearch.trim());
      const json = await apiFetch<PaginatedPlatformOrganizations>(`/admin/organizations?${q.toString()}`, {
        signal: controller.signal,
      });
      setData(json);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, [offset, debouncedSearch]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  function onSearchChange(value: string) {
    setSearch(value);
    setOffset(0);
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !loading && data !== null && data.items.length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader title={t("admin.organizationsTitle")} subtitle={t("admin.organizationsSubtitle")} />

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <label htmlFor="admin-org-search" className="sr-only">
          {t("admin.orgSearchAriaLabel")}
        </label>
        <Input
          id="admin-org-search"
          type="search"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={t("admin.orgSearchPlaceholder")}
        />
      </div>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      <div className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("common.name")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colStatus")}</th>
                <th className={`hidden md:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("admin.colOwner")}</th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("admin.colMembers")}</th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("admin.colInvoices")}</th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("admin.colQuotes")}</th>
                <th
                  className={`hidden xl:table-cell ${TABLE_HEAD_CELL_CLASS}`}
                  title={t("admin.createdApprox")}
                >
                  {t("admin.colCreated")}
                </th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {loading ? (
                <tr>
                  <td colSpan={7} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                    {t("admin.loadingOrganizations")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={7} className={TABLE_CELL_CLASS}>
                    <EmptyState
                      title={t("admin.emptyOrgsTitle")}
                      description={t("admin.emptyOrgsDescription")}
                    />
                  </td>
                </tr>
              ) : (
                data?.items.map((org) => (
                  <tr key={org.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>
                      <Link
                        href={`/admin/organizations/${org.id}`}
                        className="font-medium text-slate-900 hover:underline"
                      >
                        {org.name}
                      </Link>
                      {org.business_name ? (
                        <p className="text-xs text-slate-500">{org.business_name}</p>
                      ) : null}
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge
                        className={
                          org.status === "active"
                            ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                            : "bg-red-50 text-red-700 ring-red-200"
                        }
                      >
                        {org.status === "active" ? t("admin.statusActive") : t("admin.statusSuspended")}
                      </Badge>
                    </td>
                    <td className={`hidden md:table-cell ${TABLE_CELL_CLASS}`}>
                      {org.owner_email ?? "—"}
                    </td>
                    <td className={`hidden lg:table-cell ${TABLE_CELL_CLASS}`}>{org.members_count}</td>
                    <td className={`hidden lg:table-cell ${TABLE_CELL_CLASS}`}>{org.invoices_count}</td>
                    <td className={`hidden lg:table-cell ${TABLE_CELL_CLASS}`}>{org.quotes_count}</td>
                    <td
                      className={`hidden xl:table-cell ${TABLE_CELL_CLASS}`}
                      title={t("admin.createdApprox")}
                    >
                      {formatApproxDate(org.created_at, language)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {data && data.total > pageSize ? (
          <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span>{t("invoices.pagination", { page: currentPage, totalPages, total: data.total })}</span>
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
