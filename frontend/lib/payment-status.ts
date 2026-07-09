export const PAYMENT_STATUSES = ["pending", "paid", "overdue"] as const;

export type PaymentStatus = (typeof PAYMENT_STATUSES)[number];

export function isPaymentStatus(value: string): value is PaymentStatus {
  return (PAYMENT_STATUSES as readonly string[]).includes(value);
}

export const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = {
  pending: "Pending",
  paid: "Paid",
  overdue: "Overdue",
};

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
