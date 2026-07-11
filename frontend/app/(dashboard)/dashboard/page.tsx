"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { BusinessInsightsSection } from "@/components/dashboard/BusinessInsightsSection";
import { CurrencySelector } from "@/components/dashboard/CurrencySelector";
import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { InvoiceVolumeChart } from "@/components/dashboard/InvoiceVolumeChart";
import { PaymentStatusBreakdown } from "@/components/dashboard/PaymentStatusBreakdown";
import { PaymentStatusChart } from "@/components/dashboard/PaymentStatusChart";
import { RevenueTrendCard } from "@/components/dashboard/RevenueTrendCard";
import { RevenueTrendLineChart } from "@/components/dashboard/RevenueTrendLineChart";
import { TopCustomersChart } from "@/components/dashboard/TopCustomersChart";
import { PaymentStatusBadge } from "@/components/invoices/PaymentStatusBadge";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { getOrganizationCurrency } from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import { isPaymentStatus } from "@/lib/payment-status";
import type { DashboardAnalytics, DashboardData } from "@/lib/types";

function RecentInvoicesSkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-t border-slate-100">
          <td className="px-4 py-4 sm:px-6">
            <div className="h-4 w-20 animate-pulse rounded bg-slate-200" />
          </td>
          <td className="hidden px-4 py-4 sm:table-cell sm:px-6">
            <div className="h-4 w-24 animate-pulse rounded bg-slate-200" />
          </td>
          <td className="px-4 py-4 sm:px-6">
            <div className="h-5 w-16 animate-pulse rounded-full bg-slate-200" />
          </td>
          <td className="px-4 py-4 sm:px-6">
            <div className="h-4 w-16 animate-pulse rounded bg-slate-200" />
          </td>
          <td className="hidden px-4 py-4 sm:table-cell sm:px-6">
            <div className="h-4 w-28 animate-pulse rounded bg-slate-200" />
          </td>
        </tr>
      ))}
    </>
  );
}

// Sentinel for the non-ApiError catch branch: translated at render time
// (fresh t() every render) rather than inside the callback, since
// useTranslation()'s t is not identity-stable and depending on it from
// useCallback would either go stale or re-trigger the fetch on every
// render.
const GENERIC_LOAD_ERROR = "__generic_load_error__";

export default function DashboardPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<DashboardData | null>(null);
  const [analytics, setAnalytics] = useState<DashboardAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Hydration-safe: default to null, resolve after mount (same pattern as
  // organizationName elsewhere in this app).
  const [orgCurrency, setOrgCurrency] = useState<string | null>(null);
  const [selectedCurrency, setSelectedCurrency] = useState<string | null>(null);
  useEffect(() => {
    const code = getOrganizationCurrency();
    setOrgCurrency(code);
    setSelectedCurrency((prev) => prev ?? code);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dashboardJson, analyticsJson] = await Promise.all([
        apiFetch<DashboardData>(orgPath("dashboard")),
        apiFetch<DashboardAnalytics>(orgPath("dashboard/analytics")),
      ]);
      setData(dashboardJson);
      setAnalytics(analyticsJson);
    } catch (e) {
      setData(null);
      setAnalytics(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const showEmpty = !loading && !error && data !== null && data.total_invoices === 0;

  // Every currency the organization's own default plus every currency
  // that actually appears among its invoices — the org's currency is
  // always offered even with zero invoices in it yet. Never a fixed list:
  // adding a new supported currency elsewhere just means it can now show
  // up here too, no code change needed.
  const availableCurrencies = Array.from(
    new Set([
      ...(orgCurrency ? [orgCurrency] : []),
      ...(data?.revenue_by_currency.map((r) => r.currency_code) ?? []),
    ])
  ).sort();
  const effectiveCurrency =
    selectedCurrency ?? orgCurrency ?? availableCurrencies[0] ?? "USD";
  const selectedRevenue =
    data?.revenue_by_currency.find((r) => r.currency_code === effectiveCurrency) ?? null;
  const filteredMonthlyRevenue = (analytics?.monthly_revenue_by_currency ?? []).filter(
    (point) => point.currency_code === effectiveCurrency
  );
  const filteredTopCustomers = (analytics?.top_customers ?? []).filter(
    (row) => row.currency_code === effectiveCurrency
  );

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {t("dashboard.title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">{t("dashboard.subtitle")}</p>
        </div>
        <CurrencySelector
          currencies={availableCurrencies}
          selected={effectiveCurrency}
          onSelect={setSelectedCurrency}
          t={t}
        />
      </header>

      <BusinessInsightsSection />

      {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error === GENERIC_LOAD_ERROR ? t("dashboard.loadError") : error}
        </div>
      ) : null}

      <section
        aria-label={t("dashboard.summaryAriaLabel")}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <DashboardCard
          title={t("dashboard.totalRevenueTitle")}
          value={
            data
              ? formatCurrency(
                  selectedRevenue ? selectedRevenue.total_revenue : 0,
                  effectiveCurrency
                )
              : "—"
          }
          description={t("dashboard.totalRevenueDescription")}
          loading={loading}
        />
        <DashboardCard
          title={t("dashboard.totalInvoicesTitle")}
          value={data ? String(data.total_invoices) : "—"}
          description={t("dashboard.totalInvoicesDescription")}
          loading={loading}
        />
        <DashboardCard
          title={t("dashboard.totalCustomersTitle")}
          value={data ? String(data.total_customers) : "—"}
          description={t("dashboard.totalCustomersDescription")}
          loading={loading}
        />
      </section>

      {showEmpty ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-6 py-12 text-center">
          <h3 className="text-base font-semibold text-slate-900">
            {t("dashboard.emptyTitle")}
          </h3>
          <p className="mx-auto mt-2 max-w-sm text-sm text-slate-600">
            {t("dashboard.emptyDescription")}
          </p>
          <Link
            href="/invoices/new"
            className="mt-5 inline-flex rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800"
          >
            {t("dashboard.createInvoiceCta")}
          </Link>
        </div>
      ) : (
        <>
          <section
            aria-label={t("dashboard.revenueStatusAriaLabel")}
            className="grid grid-cols-1 gap-4 lg:grid-cols-2"
          >
            <RevenueTrendCard
              revenueThisMonth={
                selectedRevenue ? Number.parseFloat(selectedRevenue.revenue_this_month) : 0
              }
              revenueLastMonth={
                selectedRevenue ? Number.parseFloat(selectedRevenue.revenue_last_month) : 0
              }
              growthPercent={
                selectedRevenue?.revenue_growth_percent != null
                  ? Number.parseFloat(selectedRevenue.revenue_growth_percent)
                  : null
              }
              loading={loading}
            />
            <PaymentStatusBreakdown
              pending={data?.pending_invoices ?? 0}
              paid={data?.paid_invoices ?? 0}
              overdue={data?.overdue_invoices ?? 0}
              loading={loading}
            />
          </section>

          <section aria-label={t("dashboard.analyticsHeading")} className="space-y-4">
            <h2 className="text-lg font-semibold text-slate-900">
              {t("dashboard.analyticsHeading")}
            </h2>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <RevenueTrendLineChart
                data={filteredMonthlyRevenue}
                loading={loading}
              />
              <InvoiceVolumeChart
                data={analytics?.monthly_summary ?? []}
                loading={loading}
              />
              <PaymentStatusChart
                data={analytics?.invoice_count_by_status ?? []}
                loading={loading}
              />
              <TopCustomersChart
                data={filteredTopCustomers}
                loading={loading}
              />
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  {t("dashboard.recentInvoicesHeading")}
                </h2>
                <p className="text-sm text-slate-500">
                  {t("dashboard.recentInvoicesSubtitle")}
                </p>
              </div>
              <Link
                href="/invoices"
                className="text-sm font-medium text-slate-700 hover:text-slate-900"
              >
                {t("dashboard.viewAll")}
              </Link>
            </div>

            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    <tr>
                      <th className="px-4 py-3 sm:px-6">{t("invoices.colInvoice")}</th>
                      <th className="hidden px-4 py-3 sm:table-cell sm:px-6">
                        {t("invoices.colCustomer")}
                      </th>
                      <th className="px-4 py-3 sm:px-6">{t("invoices.colStatus")}</th>
                      <th className="px-4 py-3 sm:px-6">{t("invoices.colTotal")}</th>
                      <th className="hidden px-4 py-3 sm:table-cell sm:px-6">
                        {t("invoices.colCreated")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {loading ? (
                      <RecentInvoicesSkeletonRows />
                    ) : data && data.recent_invoices.length === 0 ? (
                      <tr>
                        <td
                          colSpan={5}
                          className="px-4 py-8 text-center text-slate-500 sm:px-6"
                        >
                          {t("invoices.noneYet")}
                        </td>
                      </tr>
                    ) : (
                      data?.recent_invoices.map((row) => {
                        const status = isPaymentStatus(row.payment_status)
                          ? row.payment_status
                          : "pending";

                        return (
                          <tr key={row.id} className="hover:bg-slate-50/80">
                            <td className="px-4 py-3 font-mono text-xs text-slate-900 sm:px-6">
                              {row.invoice_number}
                            </td>
                            <td className="hidden px-4 py-3 text-slate-600 sm:table-cell sm:px-6">
                              {row.customer_name ?? (
                                <span className="text-slate-400">—</span>
                              )}
                            </td>
                            <td className="px-4 py-3 sm:px-6">
                              <PaymentStatusBadge status={status} />
                            </td>
                            <td className="px-4 py-3 font-medium text-slate-900 sm:px-6">
                              {formatCurrency(row.total, row.currency_code)}
                            </td>
                            <td className="hidden px-4 py-3 text-slate-600 sm:table-cell sm:px-6">
                              {new Date(row.created_at).toLocaleString()}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
