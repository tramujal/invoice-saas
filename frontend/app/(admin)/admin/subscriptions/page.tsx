"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Input";
import { PageContainer } from "@/components/ui/PageContainer";
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
import type { PaginatedPlatformSubscriptions, SubscriptionStatus } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";
const pageSize = 20;

const STATUS_FILTERS: (SubscriptionStatus | "any")[] = [
  "any",
  "trialing",
  "active",
  "past_due",
  "paused",
  "canceled",
  "expired",
  "inactive",
];

const STATUS_BADGE_CLASS: Record<SubscriptionStatus, string> = {
  trialing: "bg-sky-50 text-sky-700 ring-sky-200",
  active: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  past_due: "bg-amber-50 text-amber-700 ring-amber-200",
  paused: "bg-slate-100 text-slate-600 ring-slate-200",
  canceled: "bg-red-50 text-red-700 ring-red-200",
  expired: "bg-red-50 text-red-700 ring-red-200",
  inactive: "bg-slate-100 text-slate-600 ring-slate-200",
};

const STATUS_LABEL_KEY: Record<SubscriptionStatus, string> = {
  trialing: "planAndLimits.statusTrialing",
  active: "planAndLimits.statusActive",
  past_due: "planAndLimits.statusPastDue",
  paused: "planAndLimits.statusPaused",
  canceled: "planAndLimits.statusCanceled",
  expired: "planAndLimits.statusExpired",
  inactive: "planAndLimits.statusInactive",
};

function formatApproxDate(value: string, locale: string): string {
  return new Date(value).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

export default function PlatformSubscriptionsPage() {
  const { t, language } = useTranslation();
  const [data, setData] = useState<PaginatedPlatformSubscriptions | null>(null);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("any");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
      if (statusFilter !== "any") q.set("status", statusFilter);
      const json = await apiFetch<PaginatedPlatformSubscriptions>(`/admin/subscriptions?${q.toString()}`, {
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
  }, [offset, statusFilter]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  function onStatusFilterChange(value: string) {
    setStatusFilter(value as (typeof STATUS_FILTERS)[number]);
    setOffset(0);
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showEmpty = !loading && data !== null && data.items.length === 0;

  return (
    <PageContainer>
      <PageHeader title={t("admin.subscriptionsTitle")} subtitle={t("admin.subscriptionsSubtitle")} />

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <label htmlFor="admin-subscription-status-filter" className="sr-only">
          {t("admin.subscriptionStatusFilterAriaLabel")}
        </label>
        <Select
          id="admin-subscription-status-filter"
          value={statusFilter}
          onChange={(e) => onStatusFilterChange(e.target.value)}
          fullWidth={false}
        >
          {STATUS_FILTERS.map((status) => (
            <option key={status} value={status}>
              {status === "any" ? t("admin.subscriptionStatusFilterAny") : t(STATUS_LABEL_KEY[status])}
            </option>
          ))}
        </Select>
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
                <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colPlan")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colStatus")}</th>
                <th className={`hidden md:table-cell ${TABLE_HEAD_CELL_CLASS}`}>
                  {t("planAndLimits.rowBillingPeriod")}
                </th>
                <th className={`hidden lg:table-cell ${TABLE_HEAD_CELL_CLASS}`}>
                  {t("planAndLimits.rowCurrentPeriodEnd")}
                </th>
                <th className={`hidden xl:table-cell ${TABLE_HEAD_CELL_CLASS}`}>
                  {t("admin.colCancelAtPeriodEnd")}
                </th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {loading ? (
                <tr>
                  <td colSpan={6} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                    {t("admin.loadingSubscriptions")}
                  </td>
                </tr>
              ) : showEmpty ? (
                <tr>
                  <td colSpan={6} className={TABLE_CELL_CLASS}>
                    <EmptyState
                      title={t("admin.emptySubscriptionsTitle")}
                      description={t("admin.emptySubscriptionsDescription")}
                    />
                  </td>
                </tr>
              ) : (
                data?.items.map((subscription) => (
                  <tr key={subscription.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>
                      <Link
                        href={`/admin/organizations/${subscription.organization_id}`}
                        className="font-medium text-slate-900 hover:underline"
                      >
                        {subscription.organization_name}
                      </Link>
                    </td>
                    <td className={TABLE_CELL_CLASS}>{subscription.plan_name}</td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge className={STATUS_BADGE_CLASS[subscription.status]}>
                        {t(STATUS_LABEL_KEY[subscription.status])}
                      </Badge>
                    </td>
                    <td className={`hidden md:table-cell ${TABLE_CELL_CLASS}`}>
                      {subscription.billing_period === "yearly"
                        ? t("planAndLimits.billingPeriodYearly")
                        : t("planAndLimits.billingPeriodMonthly")}
                    </td>
                    <td className={`hidden lg:table-cell ${TABLE_CELL_CLASS}`}>
                      {formatApproxDate(subscription.current_period_end, language)}
                    </td>
                    <td className={`hidden xl:table-cell ${TABLE_CELL_CLASS}`}>
                      {subscription.cancel_at_period_end ? (
                        <Badge className="bg-amber-50 text-amber-700 ring-amber-200">
                          {t("planAndLimits.cancelAtPeriodEndBadge")}
                        </Badge>
                      ) : (
                        "—"
                      )}
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
    </PageContainer>
  );
}
