"use client";

import { useState } from "react";

import { PaymentStatusBadge } from "@/components/invoices/PaymentStatusBadge";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  PAYMENT_STATUSES,
  PAYMENT_STATUS_SELECT_CLASS,
  getPaymentStatusLabel,
  type PaymentStatus,
} from "@/lib/payment-status";
import type { InvoiceSummary } from "@/lib/types";

type PaymentStatusSelectProps = {
  invoiceId: string;
  value: PaymentStatus;
  onUpdated: (status: PaymentStatus) => void;
  disabled?: boolean;
  /** When true, show badge beside the select (default: true). */
  showBadge?: boolean;
};

export function PaymentStatusSelect({
  invoiceId,
  value,
  onUpdated,
  disabled = false,
  showBadge = true,
}: PaymentStatusSelectProps) {
  const toast = useToast();
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);

  async function handleChange(next: PaymentStatus) {
    if (next === value || saving || disabled) return;

    const previous = value;
    onUpdated(next);

    const loadingId = toast.loading(t("status.updating"));
    setSaving(true);
    try {
      await apiFetch<InvoiceSummary>(orgPath(`invoices/${invoiceId}`), {
        method: "PATCH",
        body: JSON.stringify({ payment_status: next }),
      });
      toast.dismiss(loadingId);
      toast.success(t("status.updated", { status: getPaymentStatusLabel(t, next) }));
    } catch (err) {
      onUpdated(previous);
      toast.dismiss(loadingId);
      toast.error(formatApiError(err, t("status.updateError")));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex min-w-[8.5rem] flex-col gap-1.5 sm:flex-row sm:items-center">
      {showBadge ? <PaymentStatusBadge status={value} /> : null}
      <select
        value={value}
        disabled={disabled || saving}
        onChange={(e) => void handleChange(e.target.value as PaymentStatus)}
        aria-label={t("status.ariaLabel")}
        className={`w-full min-w-[7.5rem] rounded-lg border px-2 py-1.5 text-xs font-medium outline-none ring-slate-400 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto ${PAYMENT_STATUS_SELECT_CLASS[value]}`}
      >
        {PAYMENT_STATUSES.map((status) => (
          <option key={status} value={status}>
            {getPaymentStatusLabel(t, status)}
          </option>
        ))}
      </select>
    </div>
  );
}
