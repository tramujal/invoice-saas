"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { CashflowCalendarResponse } from "@/lib/types";

type CashCalendarSectionProps = {
  data: CashflowCalendarResponse | null;
  loading: boolean;
  granularity: "day" | "week" | "month";
  onGranularityChange: (next: "day" | "week" | "month") => void;
};

const GRANULARITIES: Array<"day" | "week" | "month"> = ["day", "week", "month"];

/** Section 7 -- the cash (receivables) calendar: currently-open invoices'
 * expected collection dates, grouped by day/week/month, within the next
 * 30 days. Deliberately never called a "cash flow" statement -- this app
 * tracks no expenses, so the disclaimer the backend returns is always
 * shown verbatim, not paraphrased away. */
export function CashCalendarSection({ data, loading, granularity, onGranularityChange }: CashCalendarSectionProps) {
  const { t } = useTranslation();

  return (
    <section aria-label={t("financial.cashCalendarHeading")} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.cashCalendarHeading")}</h2>
        <div className="flex gap-1 rounded-lg bg-slate-100 p-1 text-xs font-medium" role="group">
          {GRANULARITIES.map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => onGranularityChange(g)}
              aria-pressed={granularity === g}
              className={`rounded-md px-2.5 py-1.5 transition ${
                granularity === g ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {t(`financial.granularity.${g}`)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : !data || data.points.length === 0 ? (
        <EmptyState title={t("financial.cashCalendarEmptyTitle")} description={t("financial.cashCalendarEmptyDescription")} />
      ) : (
        <div className="space-y-2">
          {data.points.map((point, i) => (
            <div
              key={i}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
            >
              <span className="text-sm font-medium text-slate-700">
                {new Date(point.period_start).toLocaleDateString()} – {new Date(point.period_end).toLocaleDateString()}
              </span>
              <span className="text-sm text-slate-500">
                {t("financial.agingInvoiceCount", { count: String(point.invoice_count) })}
              </span>
              <span className="text-sm font-semibold text-slate-900">
                {point.currency_code} {formatMoney(Number(point.known_amount))}
              </span>
            </div>
          ))}
        </div>
      )}

      {data?.disclaimer ? <p className="text-xs text-slate-400">{data.disclaimer}</p> : null}
    </section>
  );
}
