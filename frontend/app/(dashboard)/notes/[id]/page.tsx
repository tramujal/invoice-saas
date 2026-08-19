"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { NoteStatusBadge, NoteTypeBadge } from "@/components/notes/NoteBadges";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/toast";
import { apiFetch, apiFetchBlob, orgPath } from "@/lib/api";
import { formatApiError, getApiErrorCode } from "@/lib/format-api-error";
import { getOrganizationPermissions } from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency, formatMoney } from "@/lib/money";
import { hasPermission } from "@/lib/permissions";
import type { AdjustmentNote, SendAdjustmentNoteEmailResponse } from "@/lib/types";

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

/** Credit/debit note detail (Phase 29).
 *
 * Actions are gated by STATUS, not just permission -- a draft can be
 * issued or deleted, an issued note can be downloaded or emailed, a void
 * note is read-only. The backend enforces every one of these
 * transitions independently; this page only decides what to OFFER.
 */
export default function AdjustmentNoteDetailPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const noteId = params?.id ?? "";

  const [note, setNote] = useState<AdjustmentNote | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"issue" | "void" | "delete" | "pdf" | "send" | null>(null);

  const permissions = getOrganizationPermissions();
  const canManage = hasPermission({ permissions }, "invoice.create");
  const canSend = hasPermission({ permissions }, "invoice.send");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setNote(await apiFetch<AdjustmentNote>(orgPath(`adjustment-notes/${noteId}`)));
    } catch (err) {
      setLoadError(formatApiError(err, t("notes.detailLoadError")));
    } finally {
      setLoading(false);
    }
  }, [noteId]); // eslint-disable-line react-hooks/exhaustive-deps -- t() is not memoized; including it re-triggers the fetch on every render

  useEffect(() => {
    if (noteId) void load();
  }, [noteId, load]);

  async function issue() {
    if (!note || busy) return;
    setBusy("issue");
    try {
      const updated = await apiFetch<AdjustmentNote>(orgPath(`adjustment-notes/${note.id}/issue`), {
        method: "POST",
      });
      setNote(updated);
      toast.success(t("notes.toastIssued", { number: updated.note_number }));
    } catch (err) {
      const code = getApiErrorCode(err);
      toast.error(
        code === "over_credit"
          ? t("notes.errorOverCredit")
          : formatApiError(err, t("notes.errorIssueFailed"))
      );
    } finally {
      setBusy(null);
    }
  }

  async function voidNote() {
    if (!note || busy) return;
    if (!window.confirm(t("notes.confirmVoid", { number: note.note_number }))) return;
    setBusy("void");
    try {
      const updated = await apiFetch<AdjustmentNote>(orgPath(`adjustment-notes/${note.id}/void`), {
        method: "POST",
      });
      setNote(updated);
      toast.success(t("notes.toastVoided", { number: updated.note_number }));
    } catch (err) {
      toast.error(formatApiError(err, t("notes.errorVoidFailed")));
    } finally {
      setBusy(null);
    }
  }

  async function deleteDraft() {
    if (!note || busy) return;
    if (!window.confirm(t("notes.confirmDelete", { number: note.note_number }))) return;
    setBusy("delete");
    try {
      await apiFetch(orgPath(`adjustment-notes/${note.id}`), { method: "DELETE" });
      toast.success(t("notes.toastDeleted"));
      window.location.href = `/invoices/${note.source_invoice_id}`;
    } catch (err) {
      toast.error(formatApiError(err, t("notes.errorDeleteFailed")));
      setBusy(null);
    }
  }

  async function downloadPdf() {
    if (!note || busy) return;
    setBusy("pdf");
    const loadingId = toast.loading(t("invoices.toastPreparingPdf"));
    try {
      const blob = await apiFetchBlob(orgPath(`adjustment-notes/${note.id}/pdf`));
      downloadBlob(blob, `${note.note_number}.pdf`);
      toast.dismiss(loadingId);
      toast.success(t("invoices.toastPdfDownloaded"));
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("invoices.toastPdfError")));
    } finally {
      setBusy(null);
    }
  }

  async function sendEmail() {
    if (!note || busy) return;
    setBusy("send");
    const loadingId = toast.loading(t("notes.toastSending"));
    try {
      const result = await apiFetch<SendAdjustmentNoteEmailResponse>(
        orgPath(`adjustment-notes/${note.id}/send-email`),
        { method: "POST" }
      );
      toast.dismiss(loadingId);
      toast.success(t("notes.toastSent", { email: result.sent_to }));
    } catch (err) {
      toast.dismiss(loadingId);
      const code = getApiErrorCode(err);
      toast.error(
        code === "customer_email_missing"
          ? t("notes.errorNoCustomerEmail")
          : formatApiError(err, t("notes.errorSendFailed"))
      );
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <PageContainer width="wide" spacing="8">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </PageContainer>
    );
  }

  if (loadError || !note) {
    return (
      <PageContainer width="form" spacing="8">
        <EmptyState title={t("notes.detailNotFoundTitle")} description={loadError ?? ""} />
        <Link href="/notes" className="text-sm font-medium text-slate-600 hover:text-slate-900">
          {t("notes.backToList")}
        </Link>
      </PageContainer>
    );
  }

  const currency = note.currency_code;
  const mixedTax = note.tax_groups.length > 1;
  const isDraft = note.status === "draft";
  const isIssued = note.status === "issued";

  return (
    <PageContainer width="wide" spacing="8" className="pb-12">
      <div>
        <Link href="/notes" className="text-sm font-medium text-slate-600 hover:text-slate-900">
          {t("notes.backToList")}
        </Link>
        <PageHeader
          title={note.note_number}
          subtitle={note.customer_name ?? t("invoiceDetail.noCustomer")}
          actions={
            <div className="flex flex-wrap gap-2">
              <NoteTypeBadge noteType={note.note_type} />
              <NoteStatusBadge status={note.status} />
            </div>
          }
        />
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("notes.relatedInvoice")}
            </dt>
            <dd className="mt-1 text-sm">
              <Link
                href={`/invoices/${note.source_invoice_id}`}
                className="font-medium text-slate-900 hover:underline"
              >
                {t("notes.viewInvoice")}
              </Link>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("notes.colIssueDate")}
            </dt>
            <dd className="mt-1 text-sm text-slate-900">
              {note.issue_date ?? t("notes.notIssuedYet")}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("invoiceDetail.currencyLabel")}
            </dt>
            <dd className="mt-1 text-sm text-slate-900">{currency}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("notes.reasonLabel")}
            </dt>
            <dd className="mt-1 text-sm text-slate-900">{note.reason || "—"}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t("lineItemPicker.lineItemsSectionTitle")}
        </h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[480px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="py-2 pr-3">{t("lineItemPicker.descriptionLabel")}</th>
                <th className="py-2 pr-3 text-right">{t("lineItemPicker.qtyLabel")}</th>
                <th className="py-2 pr-3 text-right">{t("lineItemPicker.unitPriceLabel")}</th>
                {mixedTax ? (
                  <th className="py-2 pr-3 text-right">{t("lineItemPicker.taxLabel")}</th>
                ) : null}
                <th className="py-2 text-right">{t("lineItemPicker.lineTotalLabel")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {note.line_items.map((line) => (
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
              {formatCurrency(Number(note.subtotal), currency)}
            </dd>
          </div>
          {mixedTax ? (
            note.tax_groups.map((group) => (
              <div key={group.rate} className="flex justify-between gap-4">
                <dt className="text-slate-600">
                  {Number(group.rate) === 0
                    ? t("documentTotals.exemptLabel")
                    : `${t("invoices.colTax")} ${Number(group.rate) * 100}%`}
                  <span className="ml-1 text-xs text-slate-400">
                    ({t("documentTotals.baseLabel")} {formatCurrency(Number(group.base), currency)})
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
                {formatCurrency(Number(note.tax_amount), currency)}
              </dd>
            </div>
          )}
          <div className="flex justify-between gap-4 border-t border-slate-200 pt-2 text-base">
            <dt className="font-semibold text-slate-800">{t("invoices.colTotal")}</dt>
            <dd className="font-semibold text-slate-900">
              {formatCurrency(Number(note.total), currency)}
            </dd>
          </div>
        </dl>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          {isDraft && canManage ? (
            <>
              <Button onClick={() => void issue()} disabled={busy !== null}>
                {busy === "issue" ? t("notes.issuing") : t("notes.issueAction")}
              </Button>
              <Button
                variant="secondary"
                onClick={() => void deleteDraft()}
                disabled={busy !== null}
              >
                {busy === "delete" ? t("notes.deleting") : t("common.delete")}
              </Button>
            </>
          ) : null}

          {isIssued ? (
            <>
              <Button variant="secondary" onClick={() => void downloadPdf()} disabled={busy !== null}>
                {t("invoices.downloadPdf")}
              </Button>
              {canSend ? (
                <Button
                  variant="secondary"
                  onClick={() => void sendEmail()}
                  disabled={busy !== null}
                >
                  {busy === "send" ? t("notes.sending") : t("notes.sendEmailAction")}
                </Button>
              ) : null}
              {canManage ? (
                <Button
                  variant="secondary"
                  onClick={() => void voidNote()}
                  disabled={busy !== null}
                  className="text-red-700"
                >
                  {busy === "void" ? t("notes.voiding") : t("notes.voidAction")}
                </Button>
              ) : null}
            </>
          ) : null}

          {note.status === "void" ? (
            <p className="text-sm text-slate-500">{t("notes.voidReadOnlyNotice")}</p>
          ) : null}
        </div>
      </section>
    </PageContainer>
  );
}
