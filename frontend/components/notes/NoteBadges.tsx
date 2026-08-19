"use client";

import { Badge } from "@/components/ui/Badge";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { AdjustmentNoteStatus, AdjustmentNoteType } from "@/lib/types";

/** Status and type pills for adjustment notes (Phase 29).
 *
 * Reuses the shared Badge, which owns shape and spacing and takes colour
 * classes only -- so these sit in the same visual language as
 * PaymentStatusBadge rather than inventing a new one.
 *
 * The palettes are chosen to carry meaning rather than decoration:
 *   draft  -> slate, the same "not yet real" grey drafts use elsewhere
 *   issued -> emerald, matching how `paid` reads as the settled state
 *   void   -> red-tinted but muted; voided is not an error, it is
 *             deliberately retired, so it must not shout like one
 *   credit -> reduces the invoice, shown in the same red family as a
 *             negative amount
 *   debit  -> increases it, shown in blue rather than green so it is
 *             never mistaken for "paid"
 */

const STATUS_CLASSES: Record<AdjustmentNoteStatus, string> = {
  draft: "bg-slate-100 text-slate-700 ring-slate-200",
  issued: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  void: "bg-rose-50 text-rose-700 ring-rose-200",
};

const TYPE_CLASSES: Record<AdjustmentNoteType, string> = {
  credit: "bg-rose-50 text-rose-700 ring-rose-200",
  debit: "bg-sky-50 text-sky-700 ring-sky-200",
};

export function NoteStatusBadge({ status }: { status: AdjustmentNoteStatus }) {
  const { t } = useTranslation();
  return <Badge className={STATUS_CLASSES[status]}>{t(`notes.status.${status}`)}</Badge>;
}

export function NoteTypeBadge({ noteType }: { noteType: AdjustmentNoteType }) {
  const { t } = useTranslation();
  return <Badge className={TYPE_CLASSES[noteType]}>{t(`notes.type.${noteType}`)}</Badge>;
}

/** The signed amount as the reader should understand it: a credit note
 * REDUCES the invoice and is shown with a leading minus, a debit note
 * increases it and is shown with a plus.
 *
 * This is presentation only. The stored amount is always positive -- see
 * docs/credit_debit_notes.md on why notes are not negative invoices. */
export function signedAmountPrefix(noteType: AdjustmentNoteType): string {
  return noteType === "credit" ? "-" : "+";
}
