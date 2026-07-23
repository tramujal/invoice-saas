"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AuditLogEntryDrawer } from "@/components/admin/AuditLogEntryDrawer";
import { type ActiveFilterChip, FilterToolbar } from "@/components/ui/FilterToolbar";
import { Badge } from "@/components/ui/Badge";
import { Input, Select } from "@/components/ui/Input";
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
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { PaginatedPlatformAuditLog, PlatformAuditLogEntry } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const GENERIC_LOAD_ERROR = "__generic_load_error__";
const pageSize = 20;

const ACTION_CODES = [
  "organization.suspended",
  "organization.reactivated",
  "user.disabled",
  "user.enabled",
  "user.email_verified",
  "user.password_reset_requested",
  "user.platform_role_granted",
  "user.platform_role_revoked",
  "platform.settings_updated",
] as const;

function actionLabel(t: TranslateFn, code: string): string {
  const key: Record<string, string> = {
    "organization.suspended": "auditLog.actionOrganizationSuspended",
    "organization.reactivated": "auditLog.actionOrganizationReactivated",
    "user.disabled": "auditLog.actionUserDisabled",
    "user.enabled": "auditLog.actionUserEnabled",
    "user.email_verified": "auditLog.actionEmailVerified",
    "user.password_reset_requested": "auditLog.actionPasswordResetRequested",
    "user.platform_role_granted": "auditLog.actionRoleGranted",
    "user.platform_role_revoked": "auditLog.actionRoleRevoked",
    "platform.settings_updated": "auditLog.actionSettingsUpdated",
  };
  const translationKey = key[code];
  return translationKey ? t(translationKey) : code;
}

function targetLabel(entry: PlatformAuditLogEntry): string {
  if (entry.target_type === "organization") return entry.target_organization_name ?? "—";
  if (entry.target_type === "user") return entry.target_user_email ?? "—";
  return "—";
}

function formatTimestamp(value: string, locale: string): string {
  return new Date(value).toLocaleString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function PlatformAuditLogPage() {
  const { t, language } = useTranslation();
  const [data, setData] = useState<PaginatedPlatformAuditLog | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<PlatformAuditLogEntry | null>(null);

  const [actorEmailSearch, setActorEmailSearch] = useState("");
  const debouncedActorEmail = useDebouncedValue(actorEmailSearch, 300);
  const [actionFilter, setActionFilter] = useState<string>("any");
  const [targetSearch, setTargetSearch] = useState("");
  const debouncedTargetSearch = useDebouncedValue(targetSearch, 300);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const hasActiveFilters =
    debouncedActorEmail.trim() !== "" ||
    actionFilter !== "any" ||
    debouncedTargetSearch.trim() !== "" ||
    dateFrom !== "" ||
    dateTo !== "";
  const isDefaultState = !hasActiveFilters;
  const dateRangeInvalid = Boolean(dateFrom && dateTo && dateFrom > dateTo);

  const filterChips: ActiveFilterChip[] = [];
  if (actionFilter !== "any") {
    const label = `${t("auditLog.filterActionLabel")}: ${actionLabel(t, actionFilter)}`;
    filterChips.push({
      key: "action",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setActionFilter)("any"),
    });
  }
  if (debouncedTargetSearch.trim() !== "") {
    const label = `${t("auditLog.filterTargetLabel")}: ${debouncedTargetSearch.trim()}`;
    filterChips.push({
      key: "target",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setTargetSearch)(""),
    });
  }
  if (dateFrom || dateTo) {
    const label = `${t("auditLog.filterDateRangeLabel")}: ${dateFrom || "…"} – ${dateTo || "…"}`;
    filterChips.push({
      key: "dateRange",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => {
        setDateFrom("");
        setDateTo("");
        setOffset(0);
      },
    });
  }

  function resetToFirstPage<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setOffset(0);
    };
  }

  function resetFilters() {
    setActorEmailSearch("");
    setActionFilter("any");
    setTargetSearch("");
    setDateFrom("");
    setDateTo("");
    setOffset(0);
  }

  const load = useCallback(async () => {
    if (dateRangeInvalid) {
      setLoading(false);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
      if (debouncedActorEmail.trim()) q.set("actor_email", debouncedActorEmail.trim());
      if (actionFilter !== "any") q.set("action", actionFilter);
      if (debouncedTargetSearch.trim()) q.set("target_search", debouncedTargetSearch.trim());
      if (dateFrom) q.set("date_from", dateFrom);
      if (dateTo) q.set("date_to", dateTo);

      const json = await apiFetch<PaginatedPlatformAuditLog>(`/admin/audit-log?${q.toString()}`, {
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
  }, [offset, debouncedActorEmail, actionFilter, debouncedTargetSearch, dateFrom, dateTo, dateRangeInvalid]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !dateRangeInvalid && !loading && data !== null && data.items.length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader title={t("auditLog.title")} subtitle={t("auditLog.subtitle")} />

      <FilterToolbar
        searchValue={actorEmailSearch}
        onSearchChange={resetToFirstPage(setActorEmailSearch)}
        searchPlaceholder={t("auditLog.actorSearchPlaceholder")}
        searchAriaLabel={t("auditLog.actorSearchAriaLabel")}
        onReset={resetFilters}
        resetLabel={t("invoices.resetFilters")}
        isDefaultState={isDefaultState}
        filtersLabel={t("common.filters")}
        chips={filterChips}
      >
        <Select
          value={actionFilter}
          onChange={(e) => resetToFirstPage(setActionFilter)(e.target.value)}
          fullWidth={false}
          aria-label={t("auditLog.filterActionLabel")}
        >
          <option value="any">{t("auditLog.filterActionLabel")}</option>
          {ACTION_CODES.map((code) => (
            <option key={code} value={code}>
              {actionLabel(t, code)}
            </option>
          ))}
        </Select>
        <Input
          type="text"
          value={targetSearch}
          onChange={(e) => resetToFirstPage(setTargetSearch)(e.target.value)}
          placeholder={t("auditLog.filterTargetPlaceholder")}
          aria-label={t("auditLog.filterTargetLabel")}
          fullWidth={false}
        />
        <label className="sr-only" htmlFor="audit-log-date-from">
          {t("auditLog.filterDateFromLabel")}
        </label>
        <Input
          id="audit-log-date-from"
          type="date"
          value={dateFrom}
          onChange={(e) => resetToFirstPage(setDateFrom)(e.target.value)}
          fullWidth={false}
        />
        <label className="sr-only" htmlFor="audit-log-date-to">
          {t("auditLog.filterDateToLabel")}
        </label>
        <Input
          id="audit-log-date-to"
          type="date"
          value={dateTo}
          onChange={(e) => resetToFirstPage(setDateTo)(e.target.value)}
          fullWidth={false}
        />
      </FilterToolbar>

      {dateRangeInvalid ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {t("auditLog.errorInvalidDateRange")}
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("auditLog.loadError") : error}
        </div>
      ) : null}

      <div className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("auditLog.colTimestamp")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("auditLog.colAction")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("auditLog.colActor")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("auditLog.colTarget")}</th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("auditLog.colReason")}</th>
                <th className={`hidden xl:table-cell ${TABLE_HEAD_CELL_CLASS}`}>{t("auditLog.colIp")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>
                  <span className="sr-only">{t("auditLog.colDetails")}</span>
                </th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {dateRangeInvalid ? null : loading ? (
                <tr>
                  <td colSpan={7} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                    {t("auditLog.loading")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={7} className={TABLE_CELL_CLASS}>
                    {hasActiveFilters ? (
                      <div className="py-6 text-center">
                        <p className="text-sm font-medium text-slate-700">{t("auditLog.emptyFilteredTitle")}</p>
                        <p className="mt-1 text-sm text-slate-500">{t("auditLog.emptyFilteredDescription")}</p>
                        <button
                          type="button"
                          onClick={resetFilters}
                          className="mt-2 text-sm font-medium text-slate-700 underline hover:text-slate-900"
                        >
                          {t("invoices.resetFilters")}
                        </button>
                      </div>
                    ) : (
                      <div className="py-6 text-center">
                        <p className="text-sm font-medium text-slate-700">{t("auditLog.emptyTitle")}</p>
                        <p className="mt-1 text-sm text-slate-500">{t("auditLog.emptyDescription")}</p>
                      </div>
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((entry) => (
                  <tr key={entry.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>{formatTimestamp(entry.created_at, language)}</td>
                    <td className={TABLE_CELL_CLASS}>
                      <span title={entry.action}>
                        <Badge className="bg-slate-100 text-slate-700 ring-slate-200">
                          {actionLabel(t, entry.action)}
                        </Badge>
                      </span>
                    </td>
                    <td className={`max-w-[160px] truncate ${TABLE_CELL_CLASS}`} title={entry.actor_email}>
                      {entry.actor_email}
                    </td>
                    <td className={`max-w-[160px] truncate ${TABLE_CELL_CLASS}`} title={targetLabel(entry)}>
                      {targetLabel(entry)}
                    </td>
                    <td
                      className={`hidden max-w-[220px] truncate lg:table-cell ${TABLE_CELL_CLASS}`}
                      title={entry.reason}
                    >
                      {entry.reason}
                    </td>
                    <td className={`hidden xl:table-cell ${TABLE_CELL_CLASS}`}>{entry.client_ip ?? "—"}</td>
                    <td className={TABLE_CELL_CLASS}>
                      <button
                        type="button"
                        onClick={() => setSelectedEntry(entry)}
                        className="text-sm font-medium text-slate-700 underline hover:text-slate-900"
                      >
                        {t("auditLog.viewDetails")}
                      </button>
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

      <AuditLogEntryDrawer
        entry={selectedEntry}
        onClose={() => setSelectedEntry(null)}
        actionLabel={(code) => actionLabel(t, code)}
        formatTimestamp={(value) => formatTimestamp(value, language)}
      />
    </div>
  );
}
