"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PaymentStatusSelect } from "@/components/invoices/PaymentStatusSelect";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch, apiFetchBlob, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { isPaymentStatus, type PaymentStatus } from "@/lib/payment-status";
import type { InvoiceSummary, PaginatedInvoices } from "@/lib/types";

const pageSize = 10;

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

export default function InvoicesPage() {
  const toast = useToast();
  const [data, setData] = useState<PaginatedInvoices | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({
        limit: String(pageSize),
        offset: String(offset),
      });
      const json = await apiFetch<PaginatedInvoices>(
        `${orgPath("invoices")}?${q.toString()}`
      );
      setData(json);
    } catch (e) {
      setData(null);
      setError(e instanceof ApiError ? e.message : "Failed to load invoices");
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => {
    void load();
  }, [load]);

  function updateInvoiceStatus(invoiceId: string, payment_status: PaymentStatus) {
    setData((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        items: prev.items.map((row) =>
          row.id === invoiceId ? { ...row, payment_status } : row
        ),
      };
    });
  }

  async function downloadInvoicePdf(invoiceId: string, invoiceNumber: string) {
    if (downloadingId) return;
    setDownloadingId(invoiceId);
    const loadingId = toast.loading("Preparing PDF…");
    try {
      const blob = await apiFetchBlob(orgPath(`invoices/${invoiceId}/pdf`));
      downloadBlob(blob, `${invoiceNumber}.pdf`);
      toast.dismiss(loadingId);
      toast.success("PDF downloaded.");
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, "Could not download PDF."));
    } finally {
      setDownloadingId(null);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const currentPage = Math.floor(offset / pageSize) + 1;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Invoices
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Newest first. Update payment status inline.
          </p>
        </div>
        <Link
          href="/invoices/new"
          className="inline-flex shrink-0 items-center justify-center rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:mt-0"
        >
          New invoice
        </Link>
      </header>

      {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-4 py-3 sm:px-6">Invoice</th>
                <th className="hidden px-4 py-3 sm:table-cell sm:px-6">Customer</th>
                <th className="px-4 py-3 sm:px-6">Status</th>
                <th className="px-4 py-3 sm:px-6">Subtotal</th>
                <th className="hidden px-4 py-3 md:table-cell md:px-6">Tax</th>
                <th className="px-4 py-3 sm:px-6">Total</th>
                <th className="hidden px-4 py-3 lg:table-cell lg:px-6">Created</th>
                <th className="px-4 py-3 sm:px-6">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-8 text-center text-slate-500 sm:px-6"
                  >
                    Loading…
                  </td>
                </tr>
              ) : data && data.items.length === 0 ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-8 text-center text-slate-500 sm:px-6"
                  >
                    No invoices yet.
                  </td>
                </tr>
              ) : (
                data?.items.map((row) => {
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
                        <PaymentStatusSelect
                          invoiceId={row.id}
                          value={status}
                          onUpdated={(next) =>
                            updateInvoiceStatus(row.id, next)
                          }
                        />
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
                      <td className="px-4 py-3 sm:px-6">
                        <button
                          type="button"
                          onClick={() =>
                            void downloadInvoicePdf(row.id, row.invoice_number)
                          }
                          disabled={downloadingId === row.id}
                          className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {downloadingId === row.id ? "Preparing…" : "Download PDF"}
                        </button>
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
              Page {currentPage} of {totalPages} · {data.total} total
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0 || loading}
                onClick={() => setOffset((o) => Math.max(0, o - pageSize))}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + pageSize >= data.total || loading}
                onClick={() => setOffset((o) => o + pageSize)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
