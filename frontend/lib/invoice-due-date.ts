import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { PaymentStatus } from "@/lib/payment-status";

/** Payment-terms presets shown on the New Invoice form -- "days" is the
 * offset added to the issue date to get the due date. 0 = due on receipt.
 * "custom" has no fixed offset; the user picks an explicit due date
 * instead. Kept in one shared file (matching lib/organization-settings.ts's
 * established pattern) so every page offering these presets stays in
 * sync. */
export const PAYMENT_TERMS_PRESETS = [
  { key: "onReceipt", days: 0 },
  { key: "net7", days: 7 },
  { key: "net15", days: 15 },
  { key: "net30", days: 30 },
  { key: "net45", days: 45 },
  { key: "net60", days: 60 },
  { key: "custom", days: null },
] as const;

export type PaymentTermsPresetKey = (typeof PAYMENT_TERMS_PRESETS)[number]["key"];

function translationKeyForPreset(key: PaymentTermsPresetKey): string {
  return `invoices.paymentTerms.${key}`;
}

export function getPaymentTermsLabel(t: TranslateFn, key: PaymentTermsPresetKey): string {
  return t(translationKeyForPreset(key));
}

/** issueDate/return value are both plain "YYYY-MM-DD" date strings (no
 * time-of-day component) -- matching how the backend stores due_date as a
 * DATE, never a datetime, so there's no timezone ambiguity to introduce
 * here either. */
export function computeDueDate(issueDate: string, days: number): string {
  const date = new Date(`${issueDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysBetween(fromDate: string, toDate: string): number {
  const from = new Date(`${fromDate}T00:00:00Z`).getTime();
  const to = new Date(`${toDate}T00:00:00Z`).getTime();
  return Math.round((to - from) / 86_400_000);
}

/** A presentation-only relative label ("Due in 3 days", "Overdue by 5
 * days", "Due today", "No due date") -- never used to decide anything
 * about the invoice's real status. `effectiveStatus` always comes from
 * the backend (InvoiceSummary.effective_payment_status); this function
 * only adds a human-friendly gloss around the due_date the backend
 * already sent, exactly like the plan's "presentation-safe relative-date
 * labels are frontend-computed" carve-out. */
export function formatDueDateRelative(
  dueDate: string | null,
  effectiveStatus: PaymentStatus,
  t: TranslateFn
): string {
  if (!dueDate) return t("invoices.dueDate.none");
  if (effectiveStatus === "paid") {
    return t("invoices.dueDate.paidOn", { date: dueDate });
  }

  const diffDays = daysBetween(todayDateString(), dueDate);
  if (diffDays === 0) return t("invoices.dueDate.today");
  if (diffDays > 0) return t("invoices.dueDate.inDays", { days: diffDays });
  return t("invoices.dueDate.overdueBy", { days: Math.abs(diffDays) });
}
