"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { type ActiveFilterChip, FilterToolbar } from "@/components/ui/FilterToolbar";
import { Select } from "@/components/ui/Input";
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
import type { PaginatedPlatformUsers } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const GENERIC_LOAD_ERROR = "__generic_load_error__";
const pageSize = 20;

type TriStateFilter = "any" | "yes" | "no";

function formatApproxDate(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

export default function PlatformUsersPage() {
  const { t, language } = useTranslation();
  const [data, setData] = useState<PaginatedPlatformUsers | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [platformRoleFilter, setPlatformRoleFilter] = useState<TriStateFilter>("any");
  const [verifiedFilter, setVerifiedFilter] = useState<TriStateFilter>("any");
  const abortRef = useRef<AbortController | null>(null);

  const hasActiveFilters =
    debouncedSearch.trim() !== "" || platformRoleFilter !== "any" || verifiedFilter !== "any";
  const isDefaultState = !hasActiveFilters;

  const filterChips: ActiveFilterChip[] = [];
  if (platformRoleFilter !== "any") {
    const label = `${t("admin.filterPlatformRoleLabel")}: ${
      platformRoleFilter === "yes" ? t("common.yes") : t("common.no")
    }`;
    filterChips.push({
      key: "platformRole",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setPlatformRoleFilter)("any"),
    });
  }
  if (verifiedFilter !== "any") {
    const label = `${t("admin.filterEmailVerifiedLabel")}: ${
      verifiedFilter === "yes" ? t("common.yes") : t("common.no")
    }`;
    filterChips.push({
      key: "verified",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setVerifiedFilter)("any"),
    });
  }

  function resetToFirstPage<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setOffset(0);
    };
  }

  function resetFilters() {
    setSearch("");
    setPlatformRoleFilter("any");
    setVerifiedFilter("any");
    setOffset(0);
  }

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
      if (debouncedSearch.trim()) q.set("search", debouncedSearch.trim());
      if (platformRoleFilter !== "any") q.set("has_platform_role", platformRoleFilter === "yes" ? "true" : "false");
      if (verifiedFilter !== "any") q.set("email_verified", verifiedFilter === "yes" ? "true" : "false");

      const json = await apiFetch<PaginatedPlatformUsers>(`/admin/users?${q.toString()}`, {
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
  }, [offset, debouncedSearch, platformRoleFilter, verifiedFilter]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !loading && data !== null && data.items.length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader title={t("admin.usersTitle")} subtitle={t("admin.usersSubtitle")} />

      <FilterToolbar
        searchValue={search}
        onSearchChange={resetToFirstPage(setSearch)}
        searchPlaceholder={t("admin.userSearchPlaceholder")}
        searchAriaLabel={t("admin.userSearchAriaLabel")}
        onReset={resetFilters}
        resetLabel={t("invoices.resetFilters")}
        isDefaultState={isDefaultState}
        filtersLabel={t("common.filters")}
        chips={filterChips}
      >
        <Select
          value={platformRoleFilter}
          onChange={(e) => resetToFirstPage(setPlatformRoleFilter)(e.target.value as TriStateFilter)}
          fullWidth={false}
          aria-label={t("admin.filterPlatformRoleLabel")}
        >
          <option value="any">{t("admin.filterPlatformRoleLabel")}</option>
          <option value="yes">{t("common.yes")}</option>
          <option value="no">{t("common.no")}</option>
        </Select>
        <Select
          value={verifiedFilter}
          onChange={(e) => resetToFirstPage(setVerifiedFilter)(e.target.value as TriStateFilter)}
          fullWidth={false}
          aria-label={t("admin.filterEmailVerifiedLabel")}
        >
          <option value="any">{t("admin.filterEmailVerifiedLabel")}</option>
          <option value="yes">{t("common.yes")}</option>
          <option value="no">{t("common.no")}</option>
        </Select>
      </FilterToolbar>

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
                <th className={TABLE_HEAD_CELL_CLASS}>{t("common.email")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colStatus")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colVerified")}</th>
                <th className={`hidden md:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("admin.colPlatformRole")}</th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("admin.colOrganizations")}</th>
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
                  <td colSpan={6} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                    {t("admin.loadingUsers")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={6} className={TABLE_CELL_CLASS}>
                    {hasActiveFilters ? (
                      <EmptyState
                        title={t("admin.emptyUsersFilteredTitle")}
                        description={t("admin.emptyUsersFilteredDescription")}
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
                      <EmptyState title={t("admin.emptyUsersTitle")} description={t("admin.emptyUsersDescription")} />
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((user) => (
                  <tr key={user.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>
                      <Link href={`/admin/users/${user.id}`} className="font-medium text-slate-900 hover:underline">
                        {user.email}
                      </Link>
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge
                        className={
                          user.status === "active"
                            ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                            : "bg-red-50 text-red-700 ring-red-200"
                        }
                      >
                        {user.status === "active" ? t("admin.statusActive") : t("admin.statusDisabled")}
                      </Badge>
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge
                        className={
                          user.email_verified
                            ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                            : "bg-slate-100 text-slate-600 ring-slate-200"
                        }
                      >
                        {user.email_verified ? t("common.yes") : t("common.no")}
                      </Badge>
                    </td>
                    <td className={`hidden md:table-cell ${TABLE_CELL_CLASS}`}>
                      {user.platform_role ?? "—"}
                    </td>
                    <td className={`hidden lg:table-cell ${TABLE_CELL_CLASS}`}>{user.organizations_count}</td>
                    <td
                      className={`hidden xl:table-cell ${TABLE_CELL_CLASS}`}
                      title={t("admin.createdApprox")}
                    >
                      {formatApproxDate(user.created_at, language)}
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
