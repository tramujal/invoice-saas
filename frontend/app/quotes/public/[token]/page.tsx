"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LanguageSwitcher } from "@/components/marketing/LanguageSwitcher";
import { useToast } from "@/components/ui/toast";
import { ApiError, authRequest, publicGet } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useMarketingTranslation } from "@/lib/i18n/useMarketingTranslation";
import { formatCurrency } from "@/lib/money";
import { QUOTE_STATUS_BADGE_CLASS, getQuoteStatusLabel } from "@/lib/quote-status";
import type { PublicQuote, PublicQuoteActionResponse } from "@/lib/types";

const defaultApi =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export default function PublicQuotePage() {
  const params = useParams<{ token: string }>();
  const toast = useToast();
  const { t, language, setLanguage } = useMarketingTranslation();

  const [quote, setQuote] = useState<PublicQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [actionPending, setActionPending] = useState<"accept" | "reject" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await publicGet<PublicQuote>(defaultApi, `/quotes/public/${params.token}`);
      setQuote(res);
      setNotFound(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
      }
      setQuote(null);
    } finally {
      setLoading(false);
    }
  }, [params.token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(action: "accept" | "reject") {
    if (actionPending) return;
    setActionPending(action);
    try {
      await authRequest<PublicQuoteActionResponse>(
        defaultApi,
        `/quotes/public/${params.token}/${action}`,
        undefined
      );
      toast.success(action === "accept" ? t("quotePublic.toastAccepted") : t("quotePublic.toastRejected"));
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("quotePublic.toastActionError")));
    } finally {
      setActionPending(null);
    }
  }

  const pdfUrl = `${defaultApi}/quotes/public/${params.token}/pdf`;

  return (
    <div className="min-h-dvh bg-slate-100 p-4 py-10">
      <div className="mx-auto w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex justify-end">
          <LanguageSwitcher language={language} setLanguage={setLanguage} t={t} />
        </div>

        {loading ? (
          <p className="mt-6 text-sm text-slate-500">{t("quotePublic.loading")}</p>
        ) : notFound || !quote ? (
          <p className="mt-6 text-sm text-red-600" role="alert">
            {t("quotePublic.notFound")}
          </p>
        ) : (
          <>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="text-xl font-semibold tracking-tight text-slate-900">
                  {quote.organization_name}
                </h1>
                <p className="mt-1 text-sm text-slate-500">
                  {t("quotePublic.quoteNumberLabel")}: {quote.quote_number}
                </p>
              </div>
              <span
                className={`inline-flex w-fit items-center rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${QUOTE_STATUS_BADGE_CLASS[quote.effective_status]}`}
              >
                {getQuoteStatusLabel(t, quote.effective_status)}
              </span>
            </div>

            {quote.customer_name ? (
              <p className="mt-4 text-sm text-slate-700">{quote.customer_name}</p>
            ) : null}

            {quote.expiry_date ? (
              <p className="mt-1 text-sm text-slate-500">
                {t("quotePublic.expiryDateLabel")}: {quote.expiry_date}
              </p>
            ) : null}

            <div className="mt-6 overflow-x-auto rounded-xl border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-4 py-2">{t("invoiceForm.descriptionLabel")}</th>
                    <th className="px-4 py-2">{t("quoteForm.qtyLabel")}</th>
                    <th className="px-4 py-2">{t("quoteForm.unitPriceLabel")}</th>
                    <th className="px-4 py-2">{t("quoteForm.lineTotalLabel")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {quote.line_items.map((item, index) => (
                    <tr key={index}>
                      <td className="px-4 py-2 text-slate-800">{item.description}</td>
                      <td className="px-4 py-2 text-slate-600">{item.quantity}</td>
                      <td className="px-4 py-2 text-slate-600">
                        {formatCurrency(item.unit_price, quote.currency_code)}
                      </td>
                      <td className="px-4 py-2 font-medium text-slate-900">
                        {formatCurrency(item.line_total, quote.currency_code)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <dl className="mt-4 space-y-2 rounded-xl bg-slate-50 p-4 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate-600">{t("quotePublic.subtotalLabel")}</dt>
                <dd className="font-medium text-slate-900">
                  {formatCurrency(quote.subtotal, quote.currency_code)}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-600">{t("quotePublic.taxLabel")}</dt>
                <dd className="font-medium text-slate-900">
                  {formatCurrency(quote.tax_amount, quote.currency_code)}
                </dd>
              </div>
              <div className="flex justify-between border-t border-slate-200 pt-2 text-base">
                <dt className="font-semibold text-slate-800">{t("quotePublic.totalLabel")}</dt>
                <dd className="font-semibold text-slate-900">
                  {formatCurrency(quote.total, quote.currency_code)}
                </dd>
              </div>
            </dl>

            {quote.notes ? (
              <div className="mt-4">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {t("quotePublic.notesLabel")}
                </h2>
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{quote.notes}</p>
              </div>
            ) : null}

            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <a
                href={pdfUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50"
              >
                {t("quotePublic.downloadPdf")}
              </a>

              {quote.effective_status === "sent" ? (
                <>
                  <button
                    type="button"
                    onClick={() => void act("accept")}
                    disabled={actionPending !== null}
                    className="inline-flex items-center justify-center rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {actionPending === "accept" ? t("quotePublic.accepting") : t("quotePublic.accept")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void act("reject")}
                    disabled={actionPending !== null}
                    className="inline-flex items-center justify-center rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-800 shadow-sm hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {actionPending === "reject" ? t("quotePublic.rejecting") : t("quotePublic.reject")}
                  </button>
                </>
              ) : (
                <p className="self-center text-sm text-slate-500">{t("quotePublic.alreadyDecided")}</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
