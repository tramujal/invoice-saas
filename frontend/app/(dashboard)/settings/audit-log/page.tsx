"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AuditEntryDetailsDrawer } from "@/components/settings/AuditEntryDetailsDrawer";
import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
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
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { AuditEntry, PaginatedAuditEntries, PaginatedMembers } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const GENERIC_LOAD_ERROR = "__generic_load_error__";
const pageSize = 20;

const EVENT_TYPES = [
  "customer.created",
  "customer.updated",
  "customer.deleted",
  "product.created",
  "product.updated",
  "product.archived",
  "product.restored",
  "quote.created",
  "quote.updated",
  "quote.deleted",
  "quote.sent",
  "quote.accepted",
  "quote.rejected",
  "quote.converted",
  "invoice.created",
  "invoice.updated",
  "invoice.sent",
  "organization.plan_changed",
] as const;

const RESOURCE_TYPES = ["customer", "product", "quote", "invoice", "organization"] as const;

function eventTypeLabel(t: TranslateFn, eventType: string): string {
  const key = `settingsAuditLog.event.${eventType.replace(".", "_")}`;
  const translated = t(key);
  return translated === key ? eventType : translated;
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

export default function SettingsAuditLogPage() {
  const { t, language } = useTranslation();
  const [data, setData] = useState<PaginatedAuditEntries | null>(null);
  const [members, setMembers] = useState<{ id: string; email: string }[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null);

  const [resourceIdSearch, setResourceIdSearch] = useState("");
  const debouncedResourceId = useDebouncedValue(resourceIdSearch, 300);
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("any");
  const [resourceTypeFilter, setResourceTypeFilter] = useState<string>("any");
  const [actorFilter, setActorFilter] = useState<string>("any");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    apiFetch<PaginatedMembers>(orgPath("members?limit=100"))
      .then((res) => setMembers(res.items.map((m) => ({ id: m.user_id, email: m.user_email }))))
      .catch(() => {
        // Non-critical: the actor filter just stays empty if this fails;
        // the rest of the page still loads via its own load() below.
      });
  }, []);

  const hasActiveFilters =
    debouncedResourceId.trim() !== "" ||
    eventTypeFilter !== "any" ||
    resourceTypeFilter !== "any" ||
    actorFilter !== "any" ||
    dateFrom !== "" ||
    dateTo !== "";
  const isDefaultState = !hasActiveFilters;
  const dateRangeInvalid = Boolean(dateFrom && dateTo && dateFrom > dateTo);

  function resetToFirstPage<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setOffset(0);
    };
  }

  function resetFilters() {
    setResourceIdSearch("");
    setEventTypeFilter("any");
    setResourceTypeFilter("any");
    setActorFilter("any");
    setDateFrom("");
    setDateTo("");
    setOffset(0);
  }

  const filterChips: ActiveFilterChip[] = [];
  if (eventTypeFilter !== "any") {
    const label = `${t("settingsAuditLog.filterEventLabel")}: ${eventTypeLabel(t, eventTypeFilter)}`;
    filterChips.push({
      key: "event",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setEventTypeFilter)("any"),
    });
  }
  if (resourceTypeFilter !== "any") {
    const label = `${t("settingsAuditLog.filterResourceTypeLabel")}: ${resourceTypeFilter}`;
    filterChips.push({
      key: "resourceType",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setResourceTypeFilter)("any"),
    });
  }
  if (actorFilter !== "any") {
    const actor = members.find((m) => m.id === actorFilter);
    const label = `${t("settingsAuditLog.filterActorLabel")}: ${actor?.email ?? actorFilter}`;
    filterChips.push({
      key: "actor",
      label,
      removeLabel: t("common.removeFilter", { label }),
      onRemove: () => resetToFirstPage(setActorFilter)("any"),
    });
  }
  if (dateFrom || dateTo) {
    const label = `${t("settingsAuditLog.filterDateRangeLabel")}: ${dateFrom || "…"} – ${dateTo || "…"}`;
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
      if (debouncedResourceId.trim()) q.set("resource_id", debouncedResourceId.trim());
      if (eventTypeFilter !== "any") q.set("event_type", eventTypeFilter);
      if (resourceTypeFilter !== "any") q.set("resource_type", resourceTypeFilter);
      if (actorFilter !== "any") q.set("actor_user_id", actorFilter);
      if (dateFrom) q.set("date_from", dateFrom);
      if (dateTo) q.set("date_to", dateTo);

      const json = await apiFetch<PaginatedAuditEntries>(orgPath(`audit-entries?${q.toString()}`), {
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
  }, [offset, debouncedResourceId, eventTypeFilter, resourceTypeFilter, actorFilter, dateFrom, dateTo, dateRangeInvalid]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !dateRangeInvalid && !loading && data !== null && data.items.length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader title={t("settingsAuditLog.title")} subtitle={t("settingsAuditLog.subtitle")} />

      <SettingsSubNav />

      <FilterToolbar
        searchValue={resourceIdSearch}
        onSearchChange={resetToFirstPage(setResourceIdSearch)}
        searchPlaceholder={t("settingsAuditLog.resourceIdSearchPlaceholder")}
        searchAriaLabel={t("settingsAuditLog.resourceIdSearchAriaLabel")}
        onReset={resetFilters}
        resetLabel={t("invoices.resetFilters")}
        isDefaultState={isDefaultState}
        filtersLabel={t("common.filters")}
        chips={filterChips}
      >
        <Select
          value={eventTypeFilter}
          onChange={(e) => resetToFirstPage(setEventTypeFilter)(e.target.value)}
          fullWidth={false}
          aria-label={t("settingsAuditLog.filterEventLabel")}
        >
          <option value="any">{t("settingsAuditLog.filterEventLabel")}</option>
          {EVENT_TYPES.map((eventType) => (
            <option key={eventType} value={eventType}>
              {eventTypeLabel(t, eventType)}
            </option>
          ))}
        </Select>
        <Select
          value={resourceTypeFilter}
          onChange={(e) => resetToFirstPage(setResourceTypeFilter)(e.target.value)}
          fullWidth={false}
          aria-label={t("settingsAuditLog.filterResourceTypeLabel")}
        >
          <option value="any">{t("settingsAuditLog.filterResourceTypeLabel")}</option>
          {RESOURCE_TYPES.map((resourceType) => (
            <option key={resourceType} value={resourceType}>
              {resourceType}
            </option>
          ))}
        </Select>
        <Select
          value={actorFilter}
          onChange={(e) => resetToFirstPage(setActorFilter)(e.target.value)}
          fullWidth={false}
          aria-label={t("settingsAuditLog.filterActorLabel")}
        >
          <option value="any">{t("settingsAuditLog.filterActorLabel")}</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.email}
            </option>
          ))}
        </Select>
        <label className="sr-only" htmlFor="settings-audit-log-date-from">
          {t("settingsAuditLog.filterDateFromLabel")}
        </label>
        <Input
          id="settings-audit-log-date-from"
          type="date"
          value={dateFrom}
          onChange={(e) => resetToFirstPage(setDateFrom)(e.target.value)}
          fullWidth={false}
        />
        <label className="sr-only" htmlFor="settings-audit-log-date-to">
          {t("settingsAuditLog.filterDateToLabel")}
        </label>
        <Input
          id="settings-audit-log-date-to"
          type="date"
          value={dateTo}
          onChange={(e) => resetToFirstPage(setDateTo)(e.target.value)}
          fullWidth={false}
        />
      </FilterToolbar>

      {dateRangeInvalid ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {t("settingsAuditLog.errorInvalidDateRange")}
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("settingsAuditLog.loadError") : error}
        </div>
      ) : null}

      <div className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("settingsAuditLog.colTimestamp")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("settingsAuditLog.colEvent")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("settingsAuditLog.colActor")}</th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>
                  {t("settingsAuditLog.colResource")}
                </th>
                <th className={TABLE_HEAD_CELL_CLASS}>
                  <span className="sr-only">{t("settingsAuditLog.colDetails")}</span>
                </th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {dateRangeInvalid ? null : loading ? (
                <tr>
                  <td colSpan={5} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                    {t("settingsAuditLog.loading")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={5} className={TABLE_CELL_CLASS}>
                    {hasActiveFilters ? (
                      <div className="py-6 text-center">
                        <p className="text-sm font-medium text-slate-700">
                          {t("settingsAuditLog.emptyFilteredTitle")}
                        </p>
                        <p className="mt-1 text-sm text-slate-500">
                          {t("settingsAuditLog.emptyFilteredDescription")}
                        </p>
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
                        <p className="text-sm font-medium text-slate-700">{t("settingsAuditLog.emptyTitle")}</p>
                        <p className="mt-1 text-sm text-slate-500">{t("settingsAuditLog.emptyDescription")}</p>
                      </div>
                    )}
                  </td>
                </tr>
              ) : (
                data?.items.map((entry) => (
                  <tr key={entry.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>{formatTimestamp(entry.created_at, language)}</td>
                    <td className={TABLE_CELL_CLASS}>
                      <span title={entry.event_type}>
                        <Badge className="bg-slate-100 text-slate-700 ring-slate-200">
                          {eventTypeLabel(t, entry.event_type)}
                        </Badge>
                      </span>
                    </td>
                    <td className={`max-w-[160px] truncate ${TABLE_CELL_CLASS}`}>
                      {entry.actor_email ?? t("settingsAuditLog.systemActor")}
                    </td>
                    <td
                      className={`hidden max-w-[220px] truncate lg:table-cell ${TABLE_CELL_CLASS}`}
                      title={`${entry.resource_type} · ${entry.resource_id}`}
                    >
                      {entry.resource_type} · {entry.resource_id}
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <button
                        type="button"
                        onClick={() => setSelectedEntry(entry)}
                        className="text-sm font-medium text-slate-700 underline hover:text-slate-900"
                      >
                        {t("settingsAuditLog.viewDetails")}
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

      <AuditEntryDetailsDrawer
        entry={selectedEntry}
        onClose={() => setSelectedEntry(null)}
        eventTypeLabel={(eventType) => eventTypeLabel(t, eventType)}
        formatTimestamp={(value) => formatTimestamp(value, language)}
      />
    </div>
  );
}
