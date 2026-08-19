"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input, Select, Textarea } from "@/components/ui/Input";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getApiErrorCode } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency, roundMoney } from "@/lib/money";
import { TAX_RATE_PRESETS, fractionFromPercent, percentFromFraction } from "@/lib/use-document-lines";
import type {
  AdjustmentNote,
  AdjustmentNoteLineInput,
  AdjustmentNoteType,
  CreditableLine,
  InvoiceCreditability,
} from "@/lib/types";

/** Create a credit or debit note from an invoice (Phase 29).
 *
 * The two modes share this page because they share almost everything --
 * the source invoice, the customer, the currency, the tax editor and the
 * grouped summary. They differ in exactly one place, which is the whole
 * reason the domain has two types:
 *
 *   CREDIT: pick from the invoice's own lines, bounded by how much of
 *           each remains creditable. Tax rates come from the source
 *           lines, never re-entered.
 *   DEBIT:  free-form positive lines for charges that were never on the
 *           invoice, so there is nothing to pick from and nothing to
 *           bound.
 *
 * Client-side limits are a convenience, never the guarantee. The backend
 * re-checks every ceiling under a row lock and is the only source of
 * truth -- see docs/credit_debit_notes.md. A 409 from the server is
 * rendered, not suppressed.
 */

type CreditRow = {
  line: CreditableLine;
  selected: boolean;
  /** What the user wants to credit against this line, in money. */
  amount: string;
};

type DebitRow = {
  key: string;
  description: string;
  quantity: string;
  unitPrice: string;
  taxPercent: string;
};

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `row-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function CreateNoteInner() {
  const { t } = useTranslation();
  const toast = useToast();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const search = useSearchParams();

  const invoiceId = params?.id ?? "";
  const noteType: AdjustmentNoteType = search?.get("type") === "debit" ? "debit" : "credit";
  const isCredit = noteType === "credit";

  const [creditability, setCreditability] = useState<InvoiceCreditability | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [creditRows, setCreditRows] = useState<CreditRow[]>([]);
  const [debitRows, setDebitRows] = useState<DebitRow[]>([
    { key: newKey(), description: "", quantity: "1", unitPrice: "", taxPercent: "22" },
  ]);
  const [reason, setReason] = useState("");
  const [issueImmediately, setIssueImmediately] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetch<InvoiceCreditability>(orgPath(`invoices/${invoiceId}/creditability`))
      .then((data) => {
        if (cancelled) return;
        setCreditability(data);
        setCreditRows(
          data.lines.map((line) => ({ line, selected: false, amount: line.remaining_creditable }))
        );
      })
      .catch((err) => {
        if (!cancelled) setLoadError(formatApiError(err, t("notes.loadInvoiceError")));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [invoiceId]); // eslint-disable-line react-hooks/exhaustive-deps -- t() is not memoized; including it re-triggers the fetch on every render

  const summary = creditability?.summary ?? null;
  const currency = summary?.currency_code ?? "USD";

  /** Live preview using the SAME grouping rule as the backend: group by
   * rate, round once per group. Doing it per line here would show a
   * total a cent away from the one that gets saved. */
  const totals = useMemo(() => {
    const bases = new Map<string, number>();
    const add = (percent: string, amount: number) => {
      const key = String(Number(percent) || 0);
      bases.set(key, roundMoney((bases.get(key) ?? 0) + amount));
    };

    if (isCredit) {
      for (const row of creditRows) {
        if (!row.selected) continue;
        const amount = Number(row.amount);
        if (!Number.isFinite(amount) || amount <= 0) continue;
        add(percentFromFraction(row.line.tax_rate), roundMoney(amount));
      }
    } else {
      for (const row of debitRows) {
        const qty = Number(row.quantity);
        const price = Number(row.unitPrice);
        if (!Number.isFinite(qty) || !Number.isFinite(price) || qty <= 0 || price < 0) continue;
        add(row.taxPercent, roundMoney(qty * price));
      }
    }

    const groups = Array.from(bases.entries())
      .map(([percent, base]) => ({ percent, base, tax: roundMoney(base * (Number(percent) / 100)) }))
      .sort((a, b) => Number(b.percent) - Number(a.percent));
    const subtotal = roundMoney(groups.reduce((acc, g) => roundMoney(acc + g.base), 0));
    const tax = roundMoney(groups.reduce((acc, g) => roundMoney(acc + g.tax), 0));
    return { groups, subtotal, tax, total: roundMoney(subtotal + tax) };
  }, [isCredit, creditRows, debitRows]);

  const remainingCreditable = Number(summary?.remaining_creditable ?? 0);
  /** Convenience guard only -- the server enforces this authoritatively. */
  const exceedsCeiling = isCredit && totals.total > remainingCreditable + 0.000001;
  const lineExceeded = isCredit
    ? creditRows.some(
        (row) => row.selected && Number(row.amount) > Number(row.line.remaining_creditable) + 0.000001
      )
    : false;
  const hasLines = isCredit
    ? creditRows.some((row) => row.selected && Number(row.amount) > 0)
    : debitRows.some((row) => Number(row.quantity) > 0 && row.unitPrice !== "");

  const creditFullRemaining = useCallback(() => {
    setCreditRows((rows) =>
      rows.map((row) => ({
        ...row,
        selected: Number(row.line.remaining_creditable) > 0,
        amount: row.line.remaining_creditable,
      }))
    );
  }, []);

  async function submit() {
    if (submitting) return;
    setSubmitError(null);

    const lines: AdjustmentNoteLineInput[] = isCredit
      ? creditRows
          .filter((row) => row.selected && Number(row.amount) > 0)
          .map((row) => ({
            description: row.line.description,
            // Amount-based crediting: one "unit" worth the credited
            // amount. Quantity stays visible on the note, but value is
            // what the backend's line ceiling counts (a partial credit
            // may be a discount, not a return).
            quantity: "1",
            unit_price: String(Number(row.amount).toFixed(2)),
            // Omitted on purpose -- the backend inherits the source
            // line's historical rate, which is the authoritative one.
            source_invoice_line_item_id: row.line.invoice_line_item_id,
          }))
      : debitRows
          .filter((row) => Number(row.quantity) > 0 && row.unitPrice !== "")
          .map((row) => ({
            description: row.description.trim(),
            quantity: row.quantity,
            unit_price: String(Number(row.unitPrice).toFixed(2)),
            tax_rate: String(fractionFromPercent(row.taxPercent)),
          }));

    if (lines.length === 0) {
      setSubmitError(t("notes.errorNeedsALine"));
      return;
    }
    if (!isCredit && lines.some((line) => !line.description)) {
      setSubmitError(t("notes.errorDescriptionRequired"));
      return;
    }

    setSubmitting(true);
    const loadingId = toast.loading(t("notes.toastCreating"));
    try {
      const note = await apiFetch<AdjustmentNote>(
        orgPath(`invoices/${invoiceId}/adjustment-notes/${noteType}`),
        {
          method: "POST",
          body: JSON.stringify({ line_items: lines, reason, issue_immediately: issueImmediately }),
        }
      );
      toast.dismiss(loadingId);
      toast.success(t("notes.toastCreated", { number: note.note_number }));
      router.push(`/notes/${note.id}`);
    } catch (err) {
      toast.dismiss(loadingId);
      const code = getApiErrorCode(err);
      // The server's own ceiling errors are surfaced verbatim in meaning
      // -- never swallowed just because the client also checked.
      if (code === "over_credit") {
        setSubmitError(t("notes.errorOverCredit"));
      } else if (code === "line_over_credit") {
        setSubmitError(t("notes.errorLineOverCredit"));
      } else {
        setSubmitError(formatApiError(err, t("notes.errorCreateFailed")));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <PageContainer width="wide" spacing="8">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-64 w-full" />
      </PageContainer>
    );
  }

  if (loadError || !summary) {
    return (
      <PageContainer width="form" spacing="8">
        <EmptyState title={t("notes.loadInvoiceErrorTitle")} description={loadError ?? ""} />
        <Link href={`/invoices/${invoiceId}`} className="text-sm font-medium text-slate-600">
          {t("notes.backToInvoice")}
        </Link>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" spacing="8" className="pb-12">
      <div>
        <Link
          href={`/invoices/${invoiceId}`}
          className="text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          {t("notes.backToInvoice")}
        </Link>
        <PageHeader
          title={isCredit ? t("notes.createCreditNote") : t("notes.createDebitNote")}
          subtitle={t("notes.createSubtitle", { currency })}
        />
      </div>

      {/* Source context: the note inherits all of this from the invoice,
          server-side. Shown read-only so the user can see what they are
          adjusting, never edit it. */}
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t("notes.relatedInvoice")}
        </h2>
        <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <dt className="text-xs text-slate-500">{t("notes.originalTotal")}</dt>
            <dd className="mt-1 text-sm font-medium text-slate-900">
              {formatCurrency(Number(summary.original_total), currency)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t("notes.adjustedTotal")}</dt>
            <dd className="mt-1 text-sm font-medium text-slate-900">
              {formatCurrency(Number(summary.adjusted_total), currency)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t("notes.remainingCreditable")}</dt>
            <dd
              className="mt-1 text-sm font-medium text-slate-900"
              data-testid="remaining-creditable"
            >
              {formatCurrency(remainingCreditable, currency)}
            </dd>
          </div>
        </dl>
      </section>

      {isCredit ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("notes.selectLinesTitle")}
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={creditFullRemaining}
              disabled={remainingCreditable <= 0}
            >
              {t("notes.creditFullRemaining")}
            </Button>
          </div>

          <div className="mt-4 space-y-3">
            {creditRows.map((row, index) => {
              const remaining = Number(row.line.remaining_creditable);
              const over = row.selected && Number(row.amount) > remaining + 0.000001;
              return (
                <div
                  key={row.line.invoice_line_item_id}
                  className="rounded-xl border border-slate-100 bg-slate-50/60 p-3 sm:p-4"
                >
                  <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
                    <div className="flex items-start gap-2 lg:col-span-5">
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300"
                        checked={row.selected}
                        disabled={remaining <= 0}
                        aria-label={t("notes.selectLineAria", { description: row.line.description })}
                        onChange={(e) =>
                          setCreditRows((rows) =>
                            rows.map((r, i) =>
                              i === index ? { ...r, selected: e.target.checked } : r
                            )
                          )
                        }
                      />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-slate-900">
                          {row.line.description}
                        </p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {t("notes.lineOriginal")}:{" "}
                          {formatCurrency(Number(row.line.line_total), currency)} ·{" "}
                          {Number(row.line.tax_rate) === 0
                            ? t("documentTotals.exemptLabel")
                            : `${Number(row.line.tax_rate) * 100}%`}
                        </p>
                      </div>
                    </div>

                    <div className="lg:col-span-4">
                      <label className="text-xs font-medium text-slate-600">
                        {t("notes.remainingOnLine")}
                      </label>
                      <p className="mt-1 flex h-[42px] items-center text-sm text-slate-700">
                        {formatCurrency(remaining, currency)}
                      </p>
                    </div>

                    <div className="lg:col-span-3">
                      <label
                        htmlFor={`credit-amount-${row.line.invoice_line_item_id}`}
                        className="text-xs font-medium text-slate-600"
                      >
                        {t("notes.amountToCredit")}
                      </label>
                      <Input
                        id={`credit-amount-${row.line.invoice_line_item_id}`}
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={row.amount}
                        disabled={!row.selected}
                        onChange={(e) =>
                          setCreditRows((rows) =>
                            rows.map((r, i) => (i === index ? { ...r, amount: e.target.value } : r))
                          )
                        }
                        className="mt-1"
                      />
                      {over ? (
                        <p className="mt-1 text-xs font-medium text-red-600">
                          {t("notes.errorLineOverCredit")}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : (
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("notes.additionalChargesTitle")}
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                setDebitRows((rows) => [
                  ...rows,
                  { key: newKey(), description: "", quantity: "1", unitPrice: "", taxPercent: "22" },
                ])
              }
            >
              {t("lineItemPicker.addLine")}
            </Button>
          </div>

          <div className="mt-4 space-y-3">
            {debitRows.map((row, index) => (
              <div key={row.key} className="rounded-xl border border-slate-100 bg-slate-50/60 p-3 sm:p-4">
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 lg:gap-4">
                  <div className="lg:col-span-4">
                    <label
                      htmlFor={`debit-desc-${row.key}`}
                      className="text-xs font-medium text-slate-600"
                    >
                      {t("lineItemPicker.descriptionLabel")}
                    </label>
                    <Input
                      id={`debit-desc-${row.key}`}
                      type="text"
                      value={row.description}
                      onChange={(e) =>
                        setDebitRows((rows) =>
                          rows.map((r, i) => (i === index ? { ...r, description: e.target.value } : r))
                        )
                      }
                      className="mt-1"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3 lg:col-span-3">
                    <div>
                      <label
                        htmlFor={`debit-qty-${row.key}`}
                        className="text-xs font-medium text-slate-600"
                      >
                        {t("lineItemPicker.qtyLabel")}
                      </label>
                      <Input
                        id={`debit-qty-${row.key}`}
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.0001"
                        value={row.quantity}
                        onChange={(e) =>
                          setDebitRows((rows) =>
                            rows.map((r, i) => (i === index ? { ...r, quantity: e.target.value } : r))
                          )
                        }
                        className="mt-1"
                      />
                    </div>
                    <div>
                      <label
                        htmlFor={`debit-price-${row.key}`}
                        className="text-xs font-medium text-slate-600"
                      >
                        {t("lineItemPicker.unitPriceLabel")}
                      </label>
                      {/* min=0: a debit line is always a positive charge.
                          Negative amounts are never how a credit is
                          expressed -- that is what credit notes are for. */}
                      <Input
                        id={`debit-price-${row.key}`}
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={row.unitPrice}
                        onChange={(e) =>
                          setDebitRows((rows) =>
                            rows.map((r, i) => (i === index ? { ...r, unitPrice: e.target.value } : r))
                          )
                        }
                        className="mt-1"
                      />
                    </div>
                  </div>
                  <div className="lg:col-span-3">
                    <label className="text-xs font-medium text-slate-600">
                      {t("lineItemPicker.taxLabel")}
                    </label>
                    {/* The Phase 28 presets, reused verbatim. */}
                    <Select
                      value={row.taxPercent}
                      onChange={(e) =>
                        setDebitRows((rows) =>
                          rows.map((r, i) => (i === index ? { ...r, taxPercent: e.target.value } : r))
                        )
                      }
                      className="mt-1"
                    >
                      {TAX_RATE_PRESETS.map((preset) => (
                        <option key={preset} value={preset}>
                          {preset === "0" ? t("lineItemPicker.taxExemptOption") : `${preset}%`}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="flex items-end lg:col-span-2">
                    <button
                      type="button"
                      onClick={() => setDebitRows((rows) => rows.filter((_, i) => i !== index))}
                      disabled={debitRows.length === 1}
                      className="mb-2 text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-40"
                    >
                      {t("common.remove")}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
        <label htmlFor="reason" className="text-sm font-medium text-slate-700">
          {t("notes.reasonLabel")}
        </label>
        <Textarea
          id="reason"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-1 max-w-2xl"
        />

        <div className="mt-6 flex justify-end">
          <dl className="w-full space-y-2 rounded-xl bg-slate-50 p-4 text-sm sm:max-w-md">
            <div className="flex justify-between gap-4">
              <dt className="text-slate-600">{t("invoices.colSubtotal")}</dt>
              <dd className="font-medium text-slate-900">
                {formatCurrency(totals.subtotal, currency)}
              </dd>
            </div>
            {totals.groups.length > 1 ? (
              totals.groups.map((group) => (
                <div key={group.percent} className="flex justify-between gap-4">
                  <dt className="text-slate-600">
                    {group.percent === "0"
                      ? t("documentTotals.exemptLabel")
                      : `${t("invoices.colTax")} ${group.percent}%`}
                    <span className="ml-1 text-xs text-slate-400">
                      ({t("documentTotals.baseLabel")} {formatCurrency(group.base, currency)})
                    </span>
                  </dt>
                  <dd className="font-medium text-slate-900">
                    {formatCurrency(group.tax, currency)}
                  </dd>
                </div>
              ))
            ) : (
              <div className="flex justify-between gap-4">
                <dt className="text-slate-600">{t("invoices.colTax")}</dt>
                <dd className="font-medium text-slate-900">{formatCurrency(totals.tax, currency)}</dd>
              </div>
            )}
            <div className="flex justify-between gap-4 border-t border-slate-200 pt-2 text-base">
              <dt className="font-semibold text-slate-800">{t("invoices.colTotal")}</dt>
              <dd className="font-semibold text-slate-900" data-testid="note-total">
                {formatCurrency(totals.total, currency)}
              </dd>
            </div>
          </dl>
        </div>

        {exceedsCeiling ? (
          <p role="alert" className="mt-4 text-sm font-medium text-red-600">
            {t("notes.errorOverCredit")}
          </p>
        ) : null}
        {submitError ? (
          <p role="alert" className="mt-4 text-sm font-medium text-red-600">
            {submitError}
          </p>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300"
              checked={issueImmediately}
              onChange={(e) => setIssueImmediately(e.target.checked)}
            />
            {t("notes.issueImmediately")}
          </label>
          <Button
            type="button"
            onClick={() => void submit()}
            disabled={submitting || !hasLines || exceedsCeiling || lineExceeded}
            className="ml-auto"
          >
            {submitting ? t("notes.creating") : t("notes.createNote")}
          </Button>
        </div>
      </section>
    </PageContainer>
  );
}

export default function CreateNotePage() {
  return (
    <Suspense fallback={null}>
      <CreateNoteInner />
    </Suspense>
  );
}
