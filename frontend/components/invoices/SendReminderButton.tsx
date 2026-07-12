"use client";

import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getApiErrorCode } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { SendInvoiceReminderResponse } from "@/lib/types";

const REMINDER_ERROR_KEYS: Record<string, string> = {
  reminders_disabled: "invoices.reminderErrorRemindersDisabled",
  invoice_already_paid: "invoices.reminderErrorAlreadyPaid",
  invoice_due_date_missing: "invoices.reminderErrorDueDateMissing",
  customer_email_missing: "invoices.reminderErrorCustomerEmailMissing",
  reminder_already_sent: "invoices.reminderErrorAlreadySent",
};

type SendReminderButtonProps = {
  invoiceId: string;
  invoiceNumber: string;
  customerName: string | null;
  disabled?: boolean;
};

/** A "Send reminder" action, confirmed before sending and rate-limited
 * server-side (shared bucket with send-email) -- see
 * app.services.invoices.send_manual_invoice_reminder. The real duplicate-
 * send guard is the backend's unique-constraint idempotency slot, not
 * anything client-side; a second click just surfaces
 * reminder_already_sent from the server. */
export function SendReminderButton({
  invoiceId,
  invoiceNumber,
  customerName,
  disabled = false,
}: SendReminderButtonProps) {
  const toast = useToast();
  const { t } = useTranslation();
  const [sending, setSending] = useState(false);

  async function handleClick() {
    if (sending || disabled) return;
    const customer = customerName ?? t("invoiceForm.noCustomerOption");
    const confirmed = window.confirm(
      t("invoices.sendReminderConfirmBody", { customer, invoice: invoiceNumber })
    );
    if (!confirmed) return;

    setSending(true);
    const loadingId = toast.loading(t("invoices.toastSendingReminder"));
    try {
      const result = await apiFetch<SendInvoiceReminderResponse>(
        orgPath(`invoices/${invoiceId}/send-reminder`),
        { method: "POST" }
      );
      toast.dismiss(loadingId);
      toast.success(t("invoices.toastReminderSent", { email: result.sent_to }));
    } catch (err) {
      toast.dismiss(loadingId);
      const code = getApiErrorCode(err);
      const key = code ? REMINDER_ERROR_KEYS[code] : undefined;
      toast.error(key ? t(key) : formatApiError(err, t("invoices.toastReminderError")));
    } finally {
      setSending(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      disabled={disabled || sending}
      className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {sending ? t("invoices.sending") : t("invoices.sendReminder")}
    </button>
  );
}
