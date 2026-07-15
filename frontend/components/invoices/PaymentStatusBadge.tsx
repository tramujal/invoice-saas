"use client";

import { Badge } from "@/components/ui/Badge";
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
    <Badge className={`${PAYMENT_STATUS_BADGE_CLASS[status]} ${className}`}>
      {getPaymentStatusLabel(t, status)}
    </Badge>
  );
}
