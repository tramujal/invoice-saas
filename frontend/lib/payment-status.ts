import type { TranslateFn } from "@/lib/i18n/useTranslation";

export const PAYMENT_STATUSES = ["pending", "paid", "overdue"] as const;

export type PaymentStatus = (typeof PAYMENT_STATUSES)[number];

/** Overdue is a derived, read-only label (see effective_payment_status) --
 * no longer something a user picks directly. PaymentStatusSelect's
 * dropdown offers only these two; PaymentStatusBadge still renders all
 * three via PAYMENT_STATUSES/PAYMENT_STATUS_BADGE_CLASS above. */
export const EDITABLE_PAYMENT_STATUSES = ["pending", "paid"] as const;

export function isPaymentStatus(value: string): value is PaymentStatus {
  return (PAYMENT_STATUSES as readonly string[]).includes(value);
}

/** Looks up the translated label for a payment status. Takes the caller's
 * own t() (from useTranslation()) rather than calling the hook itself, so
 * this stays a plain, hook-free utility module — the single source of truth
 * for these labels lives in lib/i18n/translations.ts's status.* keys. */
export function getPaymentStatusLabel(t: TranslateFn, status: PaymentStatus): string {
  return t(`status.${status}`);
}

export const PAYMENT_STATUS_BADGE_CLASS: Record<PaymentStatus, string> = {
  pending: "bg-amber-100 text-amber-900 ring-amber-200/80",
  paid: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  overdue: "bg-red-100 text-red-900 ring-red-200/80",
};

export const PAYMENT_STATUS_SELECT_CLASS: Record<PaymentStatus, string> = {
  pending: "border-amber-200 bg-amber-50 text-amber-900",
  paid: "border-emerald-200 bg-emerald-50 text-emerald-900",
  overdue: "border-red-200 bg-red-50 text-red-900",
};

/** Hex equivalents of the badge color families, for chart fills (SVG can't
 * consume Tailwind classes directly). */
export const PAYMENT_STATUS_CHART_COLOR: Record<PaymentStatus, string> = {
  pending: "#fbbf24", // amber-400
  paid: "#10b981", // emerald-500
  overdue: "#f87171", // red-400
};
