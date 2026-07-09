import {
  PAYMENT_STATUS_BADGE_CLASS,
  PAYMENT_STATUS_LABELS,
  type PaymentStatus,
} from "@/lib/payment-status";

type PaymentStatusBadgeProps = {
  status: PaymentStatus;
  className?: string;
};

export function PaymentStatusBadge({
  status,
  className = "",
}: PaymentStatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${PAYMENT_STATUS_BADGE_CLASS[status]} ${className}`}
    >
      {PAYMENT_STATUS_LABELS[status]}
    </span>
  );
}
