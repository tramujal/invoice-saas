"use client";

import { TrendIndicator } from "@/components/analytics/TrendIndicator";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import type { PeriodComparison } from "@/lib/types";

/** Counts (invoice/customer/quote) arrive quantized to 2 decimals like
 * every other Decimal in this API (e.g. "3.00") -- rounded to a plain
 * integer for display, never shown with cents. */
function formatCount(value: string): string {
  return String(Math.round(Number.parseFloat(value)));
}

function ComparisonCard({
  title,
  current,
  previous,
  comparison,
  loading,
  formatValue,
}: {
  title: string;
  current: string;
  previous: string;
  comparison: PeriodComparison;
  loading: boolean;
  formatValue: (value: string) => string;
}) {
  const { t } = useTranslation();

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
        {loading ? (
          <div className="h-5 w-16 animate-pulse rounded-full bg-slate-200" />
        ) : (
          <TrendIndicator
            direction={comparison.direction}
            percentageDifference={comparison.percentage_difference}
          />
        )}
      </div>
      {loading ? (
        <div className="mt-3 space-y-2" aria-hidden>
          <div className="h-8 w-24 animate-pulse rounded-lg bg-slate-200" />
          <div className="h-4 w-32 animate-pulse rounded bg-slate-100" />
        </div>
      ) : (
        <>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
            {formatValue(current)}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            {t("analytics.comparisonVsPrevious", { previous: formatValue(previous) })}
          </p>
        </>
      )}
    </article>
  );
}

type PeriodComparisonCardsProps = {
  revenueTrend: Record<string, PeriodComparison>;
  invoiceCountTrend: PeriodComparison;
  customerGrowthTrend: PeriodComparison;
  quoteCountTrend: PeriodComparison;
  loading: boolean;
};

/** One card per revenue currency (never combined) plus the three
 * currency-agnostic count comparisons -- every card renders current,
 * previous, and a TrendIndicator (direction + percentage), never just a
 * bare percentage, per this phase's own "do not expose only
 * percentages" requirement. */
export function PeriodComparisonCards({
  revenueTrend,
  invoiceCountTrend,
  customerGrowthTrend,
  quoteCountTrend,
  loading,
}: PeriodComparisonCardsProps) {
  const { t } = useTranslation();
  const currencies = Object.keys(revenueTrend).sort();

  return (
    <section
      aria-label={t("analytics.comparisonHeading")}
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
    >
      {currencies.map((code) => (
        <ComparisonCard
          key={code}
          title={t("analytics.comparisonRevenueTitle", { currency: code })}
          current={revenueTrend[code].current}
          previous={revenueTrend[code].previous}
          comparison={revenueTrend[code]}
          loading={loading}
          formatValue={(value) => formatCurrency(value, code)}
        />
      ))}
      <ComparisonCard
        title={t("analytics.comparisonInvoiceCountTitle")}
        current={invoiceCountTrend.current}
        previous={invoiceCountTrend.previous}
        comparison={invoiceCountTrend}
        loading={loading}
        formatValue={formatCount}
      />
      <ComparisonCard
        title={t("analytics.comparisonCustomerGrowthTitle")}
        current={customerGrowthTrend.current}
        previous={customerGrowthTrend.previous}
        comparison={customerGrowthTrend}
        loading={loading}
        formatValue={formatCount}
      />
      <ComparisonCard
        title={t("analytics.comparisonQuoteCountTitle")}
        current={quoteCountTrend.current}
        previous={quoteCountTrend.previous}
        comparison={quoteCountTrend}
        loading={loading}
        formatValue={formatCount}
      />
    </section>
  );
}
