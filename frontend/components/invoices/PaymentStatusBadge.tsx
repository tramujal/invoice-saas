"use client";

import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  PAYMENT_STATUS_BADGE_CLASS,
  getPaymentStatusLabel,
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
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${PAYMENT_STATUS_BADGE_CLASS[status]} ${className}`}
    >
      {getPaymentStatusLabel(t, status)}
    </span>
  );
}
