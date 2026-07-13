import type { TranslateFn } from "@/lib/i18n/useTranslation";

export const QUOTE_STATUSES = [
  "draft",
  "sent",
  "accepted",
  "rejected",
  "expired",
  "converted",
] as const;

export type QuoteStatus = (typeof QUOTE_STATUSES)[number];

export function isQuoteStatus(value: string): value is QuoteStatus {
  return (QUOTE_STATUSES as readonly string[]).includes(value);
}

/** Looks up the translated label for a quote status -- same hook-free
 * convention as lib/payment-status.ts's getPaymentStatusLabel. */
export function getQuoteStatusLabel(t: TranslateFn, status: QuoteStatus): string {
  return t(`quoteStatus.${status}`);
}

export const QUOTE_STATUS_BADGE_CLASS: Record<QuoteStatus, string> = {
  draft: "bg-slate-100 text-slate-700 ring-slate-200/80",
  sent: "bg-sky-100 text-sky-900 ring-sky-200/80",
  accepted: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  rejected: "bg-red-100 text-red-900 ring-red-200/80",
  expired: "bg-amber-100 text-amber-900 ring-amber-200/80",
  converted: "bg-violet-100 text-violet-900 ring-violet-200/80",
};
