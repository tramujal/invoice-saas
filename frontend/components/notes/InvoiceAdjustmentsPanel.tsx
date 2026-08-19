"use client";

import Link from "next/link";

import { ButtonLink } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import type { AdjustmentNote, InvoiceAdjustmentSummary } from "@/lib/types";

import { NoteStatusBadge, NoteTypeBadge, signedAmountPrefix } from "./NoteBadges";

/** The adjustments section of the invoice detail page (Phase 29).
 *
 * Two jobs, kept visually distinct on purpose:
 *   1. Make "original" vs "adjusted" unmissable. The original total is
 *      never relabelled or restyled -- it stays exactly what the invoice
 *      says it is -- and the adjusted figure appears BELOW it as a
 *      separate, clearly derived line.
 *   2. List the linked notes, each navigable.
 *
 * Renders nothing at all when there are no notes, so an ordinary invoice
 * is untouched by this feature.
 */
export function InvoiceAdjustmentsPanel({
  invoiceId,
  summary,
  notes,
  canCreate,
}: {
  invoiceId: string;
  summary: InvoiceAdjustmentSummary | null;
  notes: AdjustmentNote[];
  canCreate: boolean;
}) {
  const { t } = useTranslation();
  if (!summary) return null;

  const currency = summary.currency_code;
  const hasAdjustments =
    summary.issued_credit_note_count > 0 || summary.issued_debit_note_count > 0;
  const hasAnyNotes = notes.length > 0;

  if (!hasAnyNotes && !canCreate) return null;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t("notes.adjustmentsTitle")}
        </h2>
        {canCreate ? (
          <div className="flex flex-wrap gap-2">
            <ButtonLink href={`/invoices/${invoiceId}/notes/new?type=credit`} variant="secondary" size="sm">
              {t("notes.createCreditNote")}
            </ButtonLink>
            <ButtonLink href={`/invoices/${invoiceId}/notes/new?type=debit`} variant="secondary" size="sm">
              {t("notes.createDebitNote")}
            </ButtonLink>
          </div>
        ) : null}
      </div>

      {hasAdjustments ? (
        <dl className="mt-4 w-full space-y-2 rounded-xl bg-slate-50 p-4 text-sm sm:max-w-md">
          <div className="flex justify-between gap-4">
            <dt className="text-slate-600">{t("notes.originalTotal")}</dt>
            <dd className="font-medium text-slate-900">
              {formatCurrency(Number(summary.original_total), currency)}
            </dd>
          </div>
          {summary.issued_credit_note_count > 0 ? (
            <div className="flex justify-between gap-4">
              <dt className="text-slate-600">{t("notes.creditNotesLabel")}</dt>
              <dd className="font-medium text-rose-700">
                -{formatCurrency(Number(summary.credited_total), currency)}
              </dd>
            </div>
          ) : null}
          {summary.issued_debit_note_count > 0 ? (
            <div className="flex justify-between gap-4">
              <dt className="text-slate-600">{t("notes.debitNotesLabel")}</dt>
              <dd className="font-medium text-sky-700">
                +{formatCurrency(Number(summary.debited_total), currency)}
              </dd>
            </div>
          ) : null}
          <div className="flex justify-between gap-4 border-t border-slate-200 pt-2 text-base">
            <dt className="font-semibold text-slate-800">{t("notes.adjustedTotal")}</dt>
            <dd className="font-semibold text-slate-900">
              {formatCurrency(Number(summary.adjusted_total), currency)}
            </dd>
          </div>
          <p className="pt-1 text-xs text-slate-500">
            {t("notes.remainingCreditable")}:{" "}
            {formatCurrency(Number(summary.remaining_creditable), currency)}
          </p>
        </dl>
      ) : null}

      {hasAnyNotes ? (
        <ul className="mt-4 divide-y divide-slate-100 rounded-xl border border-slate-100">
          {notes.map((note) => (
            <li key={note.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5">
              <Link
                href={`/notes/${note.id}`}
                className="text-sm font-medium text-slate-900 hover:underline"
              >
                {note.note_number}
              </Link>
              <NoteTypeBadge noteType={note.note_type} />
              <NoteStatusBadge status={note.status} />
              <span className="text-xs text-slate-500">
                {note.issue_date ?? t("notes.notIssuedYet")}
              </span>
              <span
                className={`ml-auto text-sm font-medium ${
                  note.note_type === "credit" ? "text-rose-700" : "text-sky-700"
                }`}
              >
                {signedAmountPrefix(note.note_type)}
                {formatCurrency(Number(note.total), note.currency_code)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
