"use client";

import { useCallback, useEffect, useState } from "react";

import { AddCustomerForm } from "@/components/customers/AddCustomerForm";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import type { Customer } from "@/lib/types";

function CustomersEmptyState() {
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
      <h2 className="mt-4 text-lg font-semibold text-slate-900">No customers yet</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
        Add your first customer using the form above. They will appear in this list
        and can be selected when you create invoices.
      </p>
    </div>
  );
}

export default function CustomersPage() {
  const [items, setItems] = useState<Customer[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = Boolean(opts?.silent);
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const json = await apiFetch<Customer[]>(orgPath("customers"));
      setItems(json);
      if (!silent) setError(null);
    } catch (e) {
      if (!silent) {
        setItems(null);
        setError(e instanceof ApiError ? e.message : "Failed to load customers");
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const showEmpty = !loading && items !== null && items.length === 0;
  const showTable = !loading && items !== null && items.length > 0;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Customers
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Members of the selected organization.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="self-start rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 sm:self-auto"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <AddCustomerForm onCreated={() => load({ silent: true })} />

      {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-500 shadow-sm sm:px-6">
          Loading customers…
        </div>
      ) : null}

      {showEmpty ? <CustomersEmptyState /> : null}

      {showTable ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-4 py-3 sm:px-6">Name</th>
                  <th className="px-4 py-3 sm:px-6">Email</th>
                  <th className="hidden px-4 py-3 md:table-cell md:px-6">Phone</th>
                  <th className="hidden px-4 py-3 lg:table-cell lg:px-6">Address</th>
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
