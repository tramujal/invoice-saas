"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { formatMoney, roundMoney } from "@/lib/money";
import type { Customer, InvoiceSummary, PaginatedInvoices } from "@/lib/types";

const RECENT_LIMIT = 5;
const REVENUE_PAGE_SIZE = 100;

type DashboardStats = {
  invoiceCount: number;
  revenue: number;
  customerCount: number;
};

async function fetchTotalRevenue(invoiceCount: number): Promise<number> {
  if (invoiceCount === 0) return 0;

  let revenue = 0;
  let offset = 0;

  while (offset < invoiceCount) {
    const page = await apiFetch<PaginatedInvoices>(
      `${orgPath("invoices")}?limit=${REVENUE_PAGE_SIZE}&offset=${offset}`
    );
    for (const invoice of page.items) {
      const amount = Number.parseFloat(invoice.total);
      if (Number.isFinite(amount)) revenue += amount;
    }
    offset += REVENUE_PAGE_SIZE;
  }

  return roundMoney(revenue);
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentInvoices, setRecentInvoices] = useState<InvoiceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [customers, recentPage] = await Promise.all([
        apiFetch<Customer[]>(orgPath("customers")),
        apiFetch<PaginatedInvoices>(
          `${orgPath("invoices")}?limit=${RECENT_LIMIT}&offset=0`
        ),
      ]);

      const revenue = await fetchTotalRevenue(recentPage.total);

      setStats({
        invoiceCount: recentPage.total,
        revenue,
        customerCount: customers.length,
      });
      setRecentInvoices(recentPage.items);
    } catch (e) {
      setStats(null);
      setRecentInvoices([]);
      setError(e instanceof ApiError ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const showRecentEmpty =
    !loading && !error && stats !== null && recentInvoices.length === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Overview of invoices, revenue, and customers for your organization.
        </p>
      </header>

      {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      <section
        aria-label="Summary"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        <DashboardCard
          title="Total invoices"
          value={stats ? String(stats.invoiceCount) : "—"}
          description="All invoices in this organization"
          loading={loading}
        />
        <DashboardCard
          title="Total revenue"
          value={stats ? formatMoney(stats.revenue) : "—"}
          description="Sum of invoice totals"
          loading={loading}
        />
        <DashboardCard
          title="Total customers"
          value={stats ? String(stats.customerCount) : "—"}
          description="Active customer records"
          loading={loading}
        />
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Recent invoices
            </h2>
            <p className="text-sm text-slate-500">
              Latest {RECENT_LIMIT} invoices, newest first.
            </p>
          </div>
          <Link
            href="/invoices"
            className="text-sm font-medium text-slate-700 hover:text-slate-900"
          >
            View all →
          </Link>
        </div>

        {loading ? (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-4 py-3 sm:px-6">Invoice</th>
                    <th className="px-4 py-3 sm:px-6">Total</th>
                    <th className="hidden px-4 py-3 sm:table-cell sm:px-6">
                      Created
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="px-4 py-4 sm:px-6">
                        <div className="h-4 w-20 animate-pulse rounded bg-slate-200" />
                      </td>
                      <td className="px-4 py-4 sm:px-6">
                        <div className="h-4 w-16 animate-pulse rounded bg-slate-200" />
                      </td>
                      <td className="hidden px-4 py-4 sm:table-cell sm:px-6">
                        <div className="h-4 w-28 animate-pulse rounded bg-slate-200" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {showRecentEmpty ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-6 py-12 text-center">
            <h3 className="text-base font-semibold text-slate-900">
              No invoices yet
            </h3>
            <p className="mx-auto mt-2 max-w-sm text-sm text-slate-600">
              Create your first invoice to see it here and track revenue on this
              dashboard.
            </p>
            <Link
              href="/invoices/new"
              className="mt-5 inline-flex rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800"
            >
              Create invoice
            </Link>
          </div>
        ) : null}

        {!loading && recentInvoices.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-4 py-3 sm:px-6">Invoice</th>
                    <th className="hidden px-4 py-3 sm:table-cell sm:px-6">
                      Customer
                    </th>
                    <th className="px-4 py-3 sm:px-6">Subtotal</th>
                    <th className="hidden px-4 py-3 md:table-cell md:px-6">Tax</th>
                    <th className="px-4 py-3 sm:px-6">Total</th>
                    <th className="hidden px-4 py-3 lg:table-cell lg:px-6">
                      Created
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {recentInvoices.map((row) => (
                    <tr key={row.id} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3 font-mono text-xs text-slate-900 sm:px-6">
                        {row.id.slice(0, 8)}…
                      </td>
                      <td className="hidden px-4 py-3 text-slate-600 sm:table-cell sm:px-6">
                        {row.customer_id ? (
                          <span className="font-mono text-xs">
                            {row.customer_id.slice(0, 8)}…
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-800 sm:px-6">
                        {row.subtotal}
                      </td>
                      <td className="hidden px-4 py-3 text-slate-800 md:table-cell md:px-6">
                        {row.tax_amount}
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-900 sm:px-6">
                        {row.total}
                      </td>
                      <td className="hidden px-4 py-3 text-slate-600 lg:table-cell lg:px-6">
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
