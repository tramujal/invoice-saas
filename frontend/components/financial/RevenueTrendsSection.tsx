"use client";

import { useState } from "react";

import { MonthlyEvolutionChart } from "@/components/analytics/MonthlyEvolutionChart";
import { CurrencySelector } from "@/components/dashboard/CurrencySelector";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatMoney } from "@/lib/money";
import type { RevenueTrendsResponse, SeriesPoint } from "@/lib/types";

function countFormatter(value: number): string {
  return String(Math.round(value));
}

type RevenueTrendsSectionProps = {
  trends: RevenueTrendsResponse | null;
  loading: boolean;
};

/** Section 2 -- monthly revenue/collections/invoice-count charts (each
 * reusing the existing MonthlyEvolutionChart, pre-filtered to one
 * currency's series, matching that component's own established
 * convention), plus rolling averages and MoM/YoY change. YoY is only
 * ever shown when the backend actually returned a value for it (see
 * build_revenue_trends_section's own "only if data exists" note) --
 * never fabricated as 0% when there's simply no data that far back. */
export function RevenueTrendsSection({ trends, loading }: RevenueTrendsSectionProps) {
  const { t } = useTranslation();
  const currencies = Array.from(new Set((trends?.points ?? []).map((p) => p.currency_code))).sort();
  const [selected, setSelected] = useState<string | null>(null);
  const effectiveCurrency = selected && currencies.includes(selected) ? selected : currencies[0] ?? null;

  const points = effectiveCurrency ? (trends?.points ?? []).filter((p) => p.currency_code === effectiveCurrency) : [];
  const invoicedSeries: SeriesPoint[] = points.map((p) => ({
    period: p.period,
    value: p.invoiced,
    currency_code: p.currency_code,
  }));
  const collectedSeries: SeriesPoint[] = points.map((p) => ({
    period: p.period,
    value: p.collected,
    currency_code: p.currency_code,
  }));
  const invoiceCountSeries: SeriesPoint[] = points.map((p) => ({
    period: p.period,
    value: String(p.invoice_count),
    currency_code: p.currency_code,
  }));

  const mom = effectiveCurrency ? trends?.month_over_month_change_percent[effectiveCurrency] : null;
  const yoy = effectiveCurrency ? trends?.year_over_year_change_percent[effectiveCurrency] : null;
  const rolling3 = effectiveCurrency ? trends?.rolling_3_month_average[effectiveCurrency] : null;
  const rolling6 = effectiveCurrency ? trends?.rolling_6_month_average[effectiveCurrency] : null;

  return (
    <section aria-label={t("financial.revenueHeading")} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.revenueHeading")}</h2>
        {currencies.length > 1 && effectiveCurrency ? (
          <CurrencySelector currencies={currencies} selected={effectiveCurrency} onSelect={setSelected} t={t} />
        ) : null}
      </div>

      {!loading && effectiveCurrency ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("financial.momLabel")}
            </dt>
            <dd className="mt-1 text-sm font-semibold text-slate-900">
              {mom === null || mom === undefined ? t("financial.noPriorData") : `${Number(mom).toFixed(1)}%`}
            </dd>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("financial.yoyLabel")}
            </dt>
            <dd className="mt-1 text-sm font-semibold text-slate-900">
              {yoy === null || yoy === undefined ? t("financial.noPriorData") : `${Number(yoy).toFixed(1)}%`}
            </dd>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("financial.rolling3Label")}
            </dt>
            <dd className="mt-1 text-sm font-semibold text-slate-900">
              {rolling3 ? `${effectiveCurrency} ${formatMoney(Number(rolling3))}` : "—"}
            </dd>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("financial.rolling6Label")}
            </dt>
            <dd className="mt-1 text-sm font-semibold text-slate-900">
              {rolling6 ? `${effectiveCurrency} ${formatMoney(Number(rolling6))}` : "—"}
            </dd>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MonthlyEvolutionChart
          title={t("financial.monthlyRevenueTitle")}
          data={invoicedSeries}
          granularity="monthly"
          emptyMessage={t("financial.evolutionEmpty")}
          loading={loading}
          valueName={t("financial.monthlyRevenueTitle")}
          formatValue={formatMoney}
        />
        <MonthlyEvolutionChart
          title={t("financial.monthlyCollectionsTitle")}
          data={collectedSeries}
          granularity="monthly"
          emptyMessage={t("financial.evolutionEmpty")}
          loading={loading}
          valueName={t("financial.monthlyCollectionsTitle")}
          formatValue={formatMoney}
        />
        <MonthlyEvolutionChart
          title={t("financial.monthlyInvoicesTitle")}
          data={invoiceCountSeries}
          granularity="monthly"
          emptyMessage={t("financial.evolutionEmpty")}
          loading={loading}
          valueName={t("financial.monthlyInvoicesTitle")}
          formatValue={countFormatter}
        />
      </div>
    </section>
  );
}
