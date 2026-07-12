"use client";

import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { cancelAssistantAction, confirmAssistantAction } from "@/lib/api";
import { assistantErrorMessageForApiError } from "@/lib/assistant-errors";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import { getPaymentStatusLabel, isPaymentStatus } from "@/lib/payment-status";
import type { AssistantChatMessage } from "@/lib/types";

type ProposalMessage = Extract<AssistantChatMessage, { kind: "proposal" }>;

type ActionProposalCardProps = {
  message: ProposalMessage;
  onStateChange: (next: Partial<ProposalMessage>) => void;
};

function titleForAction(t: TranslateFn, action: string): string {
  if (action === "create_invoice_draft") return t("assistant.action.createInvoiceDraft.title");
  if (action === "update_invoice_status") return t("assistant.action.updateInvoiceStatus.title");
  if (action === "send_invoice_email") return t("assistant.action.sendInvoiceEmail.title");
  if (action === "send_payment_reminder") return t("assistant.action.sendPaymentReminder.title");
  return t("assistant.action.genericTitle");
}

function confirmLabelForAction(t: TranslateFn, action: string): string {
  if (action === "create_invoice_draft") return t("assistant.action.confirmCreate");
  if (action === "update_invoice_status") return t("assistant.action.confirmChange");
  if (action === "send_invoice_email") return t("assistant.action.confirmSend");
  if (action === "send_payment_reminder") return t("assistant.action.confirmSend");
  return t("assistant.action.genericConfirm");
}

function formatPercent(fraction: unknown): string {
  const n = Number(fraction);
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : String(fraction ?? "");
}

function SummaryRow({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className={bold ? "font-semibold text-slate-900" : "text-slate-800"}>{value}</span>
    </div>
  );
}

function renderSummary(t: TranslateFn, action: string, summary: Record<string, unknown>) {
  const currency = typeof summary.currency_code === "string" ? summary.currency_code : "";

  if (action === "create_invoice_draft") {
    const lineItems = Array.isArray(summary.line_items)
      ? (summary.line_items as Array<Record<string, unknown>>)
      : [];
    return (
      <>
        <SummaryRow label={t("invoices.colCustomer")} value={String(summary.customer_name ?? "")} />
        <SummaryRow label={t("common.currencyLabel")} value={currency} />
        {lineItems.map((line, index) => (
          <div key={index} className="rounded-lg bg-slate-50 px-2.5 py-2">
            <p className="text-slate-800">{String(line.description ?? "")}</p>
            <div className="mt-1 flex gap-4 text-xs text-slate-500">
              <span>
                {t("invoiceForm.qtyLabel")}: {String(line.quantity ?? "")}
              </span>
              <span>
                {t("invoiceForm.unitPriceLabel")}: {currency} {String(line.unit_price ?? "")}
              </span>
            </div>
          </div>
        ))}
        <SummaryRow label={t("assistant.action.taxRateLabel")} value={formatPercent(summary.tax_rate)} />
        <SummaryRow
          label={t("invoices.colSubtotal")}
          value={`${currency} ${String(summary.subtotal ?? "")}`}
        />
        <SummaryRow label={t("invoices.colTax")} value={`${currency} ${String(summary.tax_amount ?? "")}`} />
        <SummaryRow
          label={t("invoices.colTotal")}
          value={`${currency} ${String(summary.total ?? "")}`}
          bold
        />
      </>
    );
  }

  if (action === "update_invoice_status") {
    const oldStatus = String(summary.old_status ?? "");
    const newStatus = String(summary.new_status ?? "");
    return (
      <>
        <SummaryRow label={t("invoices.colInvoice")} value={String(summary.invoice_number ?? "")} />
        <SummaryRow
          label={t("assistant.action.currentLabel")}
          value={isPaymentStatus(oldStatus) ? getPaymentStatusLabel(t, oldStatus) : oldStatus}
        />
        <SummaryRow
          label={t("assistant.action.newLabel")}
          value={isPaymentStatus(newStatus) ? getPaymentStatusLabel(t, newStatus) : newStatus}
          bold
        />
      </>
    );
  }

  if (action === "send_invoice_email") {
    return (
      <>
        <SummaryRow label={t("invoices.colInvoice")} value={String(summary.invoice_number ?? "")} />
        <SummaryRow
          label={t("assistant.action.recipientLabel")}
          value={String(summary.recipient_email ?? "")}
        />
      </>
    );
  }

  if (action === "send_payment_reminder") {
    const daysUntilDue = summary.days_until_due;
    const daysOverdue = summary.days_overdue;
    return (
      <>
        <SummaryRow label={t("invoices.colInvoice")} value={String(summary.invoice_number ?? "")} />
        <SummaryRow label={t("invoices.colCustomer")} value={String(summary.customer_name ?? "")} />
        <SummaryRow
          label={t("assistant.action.recipientLabel")}
          value={String(summary.recipient_email ?? "")}
        />
        <SummaryRow label={t("invoices.colDueDate")} value={String(summary.due_date ?? "")} />
        {typeof daysOverdue === "number" ? (
          <SummaryRow
            label={t("invoices.dueDate.overdueBy", { days: daysOverdue })}
            value=""
          />
        ) : typeof daysUntilDue === "number" ? (
          <SummaryRow
            label={t("invoices.dueDate.inDays", { days: daysUntilDue })}
            value=""
          />
        ) : null}
        <SummaryRow label={t("invoices.colTotal")} value={String(summary.total ?? "")} bold />
      </>
    );
  }

  // Generic fallback so a brand-new action type (added later purely as a
  // backend tool — see app/ai/tools/registry.py) still renders something
  // reasonable with zero frontend changes required.
  return Object.entries(summary).map(([key, value]) => (
    <SummaryRow
      key={key}
      label={key}
      value={typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}
    />
  ));
}

export function ActionProposalCard({ message, onStateChange }: ActionProposalCardProps) {
  const { t } = useTranslation();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const isTerminal =
    message.status === "executed" || message.status === "cancelled" || message.status === "error";
  const disabled = busy || isTerminal;

  async function handleConfirm() {
    if (disabled) return;
    setBusy(true);
    onStateChange({ status: "executing" });
    try {
      const result = await confirmAssistantAction(message.proposalId);
      onStateChange({ status: "executed", resultSummary: result.summary });
      toast.success(t("assistant.action.toastConfirmed"));
    } catch (err) {
      onStateChange({ status: "error" });
      toast.error(assistantErrorMessageForApiError(t, err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (disabled) return;
    setBusy(true);
    onStateChange({ status: "cancelling" });
    try {
      await cancelAssistantAction(message.proposalId);
      onStateChange({ status: "cancelled" });
      toast.success(t("assistant.action.toastCancelled"));
    } catch (err) {
      // Restore to pending -- a failed cancel attempt (e.g. it had
      // already expired server-side) shouldn't strand the card in a
      // permanently-disabled "cancelling" state if it's actually still
      // pending; re-fetch semantics aren't needed here since the only
      // failure modes are terminal-state ones the buttons already guard.
      onStateChange({ status: "pending" });
      toast.error(assistantErrorMessageForApiError(t, err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-[85%] rounded-2xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {titleForAction(t, message.action)}
      </p>

      <div className="mt-2 space-y-1.5">{renderSummary(t, message.action, message.summary)}</div>

      {isTerminal ? (
        <p
          className={`mt-3 text-xs font-medium ${
            message.status === "executed"
              ? "text-emerald-700"
              : message.status === "cancelled"
                ? "text-slate-500"
                : "text-red-700"
          }`}
        >
          {message.status === "executed"
            ? t("assistant.action.stateExecuted")
            : message.status === "cancelled"
              ? t("assistant.action.stateCancelled")
              : t("assistant.action.stateError")}
        </p>
      ) : (
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={disabled}
            className="inline-flex items-center justify-center rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {message.status === "executing"
              ? t("assistant.action.stateExecuting")
              : confirmLabelForAction(t, message.action)}
          </button>
          <button
            type="button"
            onClick={() => void handleCancel()}
            disabled={disabled}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {t("common.cancel")}
          </button>
        </div>
      )}
    </div>
  );
}
