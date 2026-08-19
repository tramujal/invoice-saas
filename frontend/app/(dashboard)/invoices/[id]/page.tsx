"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { InvoiceAdjustmentsPanel } from "@/components/notes/InvoiceAdjustmentsPanel";
import { PaymentStatusBadge } from "@/components/invoices/PaymentStatusBadge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/toast";
import { apiFetch, apiFetchBlob, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency, formatMoney } from "@/lib/money";
import { hasPermission } from "@/lib/permissions";
import { getOrganizationPermissions } from "@/lib/auth-storage";
import type {
  AdjustmentNote,
  InvoiceCreditability,
  InvoiceCreatedResponse,
  InvoiceLineItemResponse,
  TaxGroup,
} from "@/lib/types";

/** Invoice detail (Phase 29).
 *
 * Added in this phase because the app had no invoice detail route at all
 * -- every invoice action lived as a row action in the list. Credit and
 * debit notes need a host page: somewhere to show the ORIGINAL versus
 * ADJUSTED value and to list the linked notes. This is that page, kept
 * deliberately focused rather than duplicating every list action.
 */
/** Same local helper the invoices list uses -- kept local rather than
 * extracted, so this page introduces no shared-module churn for six
 * lines of DOM plumbing. */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}


export default function InvoiceDetailPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const invoiceId = params?.id ?? "";

  const [invoice, setInvoice] = useState<InvoiceCreatedResponse | null>(null);
  const [creditability, setCreditability] = useState<InvoiceCreditability | null>(null);
  const [notes, setNotes] = useState<AdjustmentNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const permissions = getOrganizationPermissions();
  const canCreateNotes = hasPermission({ permissions }, "invoice.create");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // Three independent reads, issued together: the page is useless
      // without the invoice, and the adjustment panels are useless
      // without the other two, so serialising them would only add
      // latency.
      const [invoiceData, creditabilityData, notesData] = await Promise.all([
        apiFetch<InvoiceCreatedResponse>(orgPath(`invoices/${invoiceId}`)),
        apiFetch<InvoiceCreditability>(orgPath(`invoices/${invoiceId}/creditability`)),
        apiFetch<AdjustmentNote[]>(orgPath(`invoices/${invoiceId}/adjustment-notes`)),
      ]);
      setInvoice(invoiceData);
      setCreditability(creditabilityData);
      setNotes(notesData);
    } catch (err) {
      setLoadError(formatApiError(err, t("invoiceDetail.loadError")));
    } finally {
      setLoading(false);
    }
  }, [invoiceId]); // eslint-disable-line react-hooks/exhaustive-deps -- t() is not memoized; including it re-triggers the fetch on every render

  useEffect(() => {
    if (invoiceId) void load();
  }, [invoiceId, load]);

  async function downloadPdf() {
    if (!invoice || downloading) return;
    setDownloading(true);
    const loadingId = toast.loading(t("invoices.toastPreparingPdf"));
    try {
      const blob = await apiFetchBlob(orgPath(`invoices/${invoice.id}/pdf`));
      downloadBlob(blob, `${invoice.invoice_number}.pdf`);
      toast.dismiss(loadingId);
      toast.success(t("invoices.toastPdfDownloaded"));
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("invoices.toastPdfError")));
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return (
      <PageContainer width="wide" spacing="8">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
      </PageContainer>
    );
  }

  if (loadError || !invoice) {
    return (
      <PageContainer width="form" spacing="8">
        <EmptyState
          title={t("invoiceDetail.notFoundTitle")}
          description={loadError ?? t("invoiceDetail.notFoundBody")}
        />
        <Link href="/invoices" className="text-sm font-medium text-slate-600 hover:text-slate-900">
          {t("invoiceDetail.backToInvoices")}
        </Link>
      </PageContainer>
    );
  }

  const currency = invoice.currency_code;
  const mixedTax = invoice.tax_groups.length > 1;

  return (
    <PageContainer width="wide" spacing="8" className="pb-12">
      <div>
        <Link href="/invoices" className="text-sm font-medium text-slate-600 hover:text-slate-900">
          {t("invoiceDetail.backToInvoices")}
        </Link>
        <PageHeader
          title={invoice.invoice_number}
          subtitle={invoice.customer_name ?? t("invoiceDetail.noCustomer")}
          actions={
            <Button variant="secondary" onClick={() => void downloadPdf()} disabled={downloading}>
              {t("invoices.downloadPdf")}
            </Button>
          }
        />
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("invoices.colStatus")}
            </dt>
            <dd className="mt-1">
              <PaymentStatusBadge status={invoice.effective_payment_status} />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("invoices.colDueDate")}
            </dt>
            <dd className="mt-1 text-sm text-slate-900">
              {invoice.due_date ?? t("invoiceDetail.noDueDate")}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("invoiceDetail.currencyLabel")}
            </dt>
            <dd className="mt-1 text-sm text-slate-900">{currency}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t("lineItemPicker.lineItemsSectionTitle")}
        </h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="py-2 pr-3">{t("lineItemPicker.descriptionLabel")}</th>
                <th className="py-2 pr-3 text-right">{t("lineItemPicker.qtyLabel")}</th>
                <th className="py-2 pr-3 text-right">{t("lineItemPicker.unitPriceLabel")}</th>
                {/* The per-line tax column follows the same rule as the
                    PDF (Phase 28): shown only when rates actually differ,
                    so a single-rate invoice is not cluttered. */}
                {mixedTax ? (
                  <th className="py-2 pr-3 text-right">{t("lineItemPicker.taxLabel")}</th>
                ) : null}
                <th className="py-2 text-right">{t("lineItemPicker.lineTotalLabel")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {invoice.line_items.map((line: InvoiceLineItemResponse) => (
                <tr key={line.id}>
                  <td className="py-2 pr-3 text-slate-900">{line.description}</td>
                  <td className="py-2 pr-3 text-right text-slate-700">{Number(line.quantity)}</td>
                  <td className="py-2 pr-3 text-right text-slate-700">
                    {formatMoney(Number(line.unit_price))}
                  </td>
                  {mixedTax ? (
                    <td className="py-2 pr-3 text-right text-slate-700">
                      {Number(line.tax_rate) === 0
                        ? t("documentTotals.exemptLabel")
                        : `${Number(line.tax_rate) * 100}%`}
                    </td>
                  ) : null}
                  <td className="py-2 text-right font-medium text-slate-900">
                    {formatMoney(Number(line.line_total))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <dl className="mt-6 ml-auto w-full space-y-2 rounded-xl bg-slate-50 p-4 text-sm sm:max-w-md">
          <div className="flex justify-between gap-4">
            <dt className="text-slate-600">{t("invoices.colSubtotal")}</dt>
            <dd className="font-medium text-slate-900">
              {formatCurrency(Number(invoice.subtotal), currency)}
            </dd>
          </div>
          {mixedTax ? (
            invoice.tax_groups.map((group: TaxGroup) => (
              <div key={group.rate} className="flex justify-between gap-4">
                <dt className="text-slate-600">
                  {Number(group.rate) === 0
                    ? t("documentTotals.exemptLabel")
                    : `${t("invoices.colTax")} ${Number(group.rate) * 100}%`}
                  <span className="ml-1 text-xs text-slate-400">
                    ({t("documentTotals.baseLabel")}{" "}
                    {formatCurrency(Number(group.base), currency)})
                  </span>
                </dt>
                <dd className="font-medium text-slate-900">
                  {formatCurrency(Number(group.tax), currency)}
                </dd>
              </div>
            ))
          ) : (
            <div className="flex justify-between gap-4">
              <dt className="text-slate-600">{t("invoices.colTax")}</dt>
              <dd className="font-medium text-slate-900">
                {formatCurrency(Number(invoice.tax_amount), currency)}
              </dd>
            </div>
          )}
          <div className="flex justify-between gap-4 border-t border-slate-200 pt-2 text-base">
            <dt className="font-semibold text-slate-800">{t("notes.originalTotal")}</dt>
            <dd className="font-semibold text-slate-900">
              {formatCurrency(Number(invoice.total), currency)}
            </dd>
          </div>
        </dl>
      </section>

      <InvoiceAdjustmentsPanel
        invoiceId={invoice.id}
        summary={creditability?.summary ?? null}
        notes={notes}
        canCreate={canCreateNotes}
      />
    </PageContainer>
  );
}
