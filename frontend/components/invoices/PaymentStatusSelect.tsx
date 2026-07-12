"use client";

import { useState } from "react";

import { PaymentStatusBadge } from "@/components/invoices/PaymentStatusBadge";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  EDITABLE_PAYMENT_STATUSES,
  PAYMENT_STATUS_SELECT_CLASS,
  getPaymentStatusLabel,
  type PaymentStatus,
} from "@/lib/payment-status";
import type { InvoiceSummary } from "@/lib/types";

type PaymentStatusSelectProps = {
  invoiceId: string;
  /** The raw, editable payment_status -- what the select actually PATCHes. */
  value: PaymentStatus;
  /** The derived, due-date-aware status to display in the badge (see
   * Invoice.effective_payment_status) -- defaults to `value` for callers
   * that don't have it, but every list/detail view should pass it so the
   * badge never shows a stale "Pending" for something actually overdue. */
  effectiveValue?: PaymentStatus;
  onUpdated: (status: PaymentStatus) => void;
  disabled?: boolean;
  /** When true, show badge beside the select (default: true). */
  showBadge?: boolean;
};

export function PaymentStatusSelect({
  invoiceId,
  value,
  effectiveValue,
  onUpdated,
  disabled = false,
  showBadge = true,
}: PaymentStatusSelectProps) {
  const toast = useToast();
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);

  // Overdue is a derived label now, never a value this select edits --
  // a legacy invoice whose stored payment_status is literally "overdue"
  // (pre-due-date data) is shown here as "Pending", exactly like every
  // other still-unpaid invoice; picking Paid still works normally.
  const selectValue: PaymentStatus = value === "overdue" ? "pending" : value;
  const badgeValue = effectiveValue ?? value;

  async function handleChange(next: PaymentStatus) {
    if (next === selectValue || saving || disabled) return;

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
      {showBadge ? <PaymentStatusBadge status={badgeValue} /> : null}
      <select
        value={selectValue}
        disabled={disabled || saving}
        onChange={(e) => void handleChange(e.target.value as PaymentStatus)}
        aria-label={t("status.ariaLabel")}
        className={`w-full min-w-[7.5rem] rounded-lg border px-2 py-1.5 text-xs font-medium outline-none ring-slate-400 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto ${PAYMENT_STATUS_SELECT_CLASS[selectValue]}`}
      >
        {EDITABLE_PAYMENT_STATUSES.map((status) => (
          <option key={status} value={status}>
            {getPaymentStatusLabel(t, status)}
          </option>
        ))}
      </select>
    </div>
  );
}
