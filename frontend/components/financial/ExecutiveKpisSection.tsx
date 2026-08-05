"use client";

import { FinancialKpiCard } from "@/components/financial/FinancialKpiCard";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { ExecutiveOverviewResponse } from "@/lib/types";

type ExecutiveKpisSectionProps = {
  overview: ExecutiveOverviewResponse | null;
  loading: boolean;
};

const PLACEHOLDER_METRIC = {
  id: "placeholder",
  label: "",
  value: null,
  currency_code: null,
  period: null,
  comparison_period: null,
  previous_value: null,
  percent_change: null,
  trend_direction: null,
  data_completeness: "insufficient" as const,
  formula_key: "",
  note: null,
};

/** Section 1 -- the 8 Executive KPI cards. Currency behavior (requirement
 * 8): every money-shaped KPI is grouped per currency, one full card grid
 * per currency present in the data -- never summed across currencies.
 * Quote conversion rate is currency-agnostic (a ratio of quote counts,
 * not money) and renders once, after the per-currency blocks. */
export function ExecutiveKpisSection({ overview, loading }: ExecutiveKpisSectionProps) {
  const { t } = useTranslation();
  const currencies = overview?.by_currency ?? [];
  const multiCurrency = currencies.length > 1;

  const rows = loading || currencies.length === 0 ? [null] : currencies;

  return (
    <section aria-label={t("financial.kpisHeading")} className="space-y-6">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.kpisHeading")}</h2>

      {rows.map((row, index) => (
        <div key={row?.currency_code ?? index} className="space-y-3">
          {multiCurrency && row ? (
            <h3 className="text-sm font-semibold text-slate-600">{row.currency_code}</h3>
          ) : null}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <FinancialKpiCard
              metric={row?.invoiced_this_month ?? PLACEHOLDER_METRIC}
              format="currency"
              label={t("financial.metricLabel.invoicedThisMonth")}
              tooltip={t("financial.tooltip.invoicedThisMonth")}
              noComparisonCaption={t("financial.noComparison.insufficientData")}
              loading={loading}
            />
            <FinancialKpiCard
              metric={row?.collected_this_month ?? PLACEHOLDER_METRIC}
              format="currency"
              label={t("financial.metricLabel.collectedThisMonth")}
              tooltip={t("financial.tooltip.collectedThisMonth")}
              noComparisonCaption={t("financial.noComparison.insufficientData")}
              loading={loading}
            />
            <FinancialKpiCard
              metric={row?.outstanding_receivables ?? PLACEHOLDER_METRIC}
              format="currency"
              label={t("financial.metricLabel.outstandingReceivables")}
              tooltip={t("financial.tooltip.outstandingReceivables")}
              noComparisonCaption={t("financial.noComparison.insufficientData")}
              loading={loading}
            />
            <FinancialKpiCard
              metric={row?.overdue_receivables ?? PLACEHOLDER_METRIC}
              format="currency"
              label={t("financial.metricLabel.overdueReceivables")}
              tooltip={t("financial.tooltip.overdueReceivables")}
              noComparisonCaption={t("financial.noComparison.insufficientData")}
              loading={loading}
            />
            <FinancialKpiCard
              metric={row?.expected_collections_next_30_days ?? PLACEHOLDER_METRIC}
              format="currency"
              label={t("financial.metricLabel.expectedCollections")}
              tooltip={t("financial.tooltip.expectedCollections")}
              noComparisonCaption={t("financial.noComparison.expectedCollections")}
              loading={loading}
            />
            <FinancialKpiCard
              metric={row?.average_invoice_value ?? PLACEHOLDER_METRIC}
              format="currency"
              label={t("financial.metricLabel.averageInvoiceValue")}
              tooltip={t("financial.tooltip.averageInvoiceValue")}
              noComparisonCaption={t("financial.noComparison.insufficientData")}
              loading={loading}
            />
            <FinancialKpiCard
              metric={row?.collection_rate ?? PLACEHOLDER_METRIC}
              format="percent"
              label={t("financial.metricLabel.collectionRate")}
              tooltip={t("financial.tooltip.collectionRate")}
              noComparisonCaption={t("financial.noComparison.insufficientData")}
              loading={loading}
            />
          </div>
        </div>
      ))}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <FinancialKpiCard
          metric={overview?.quote_conversion_rate ?? PLACEHOLDER_METRIC}
          format="percent"
          label={t("financial.metricLabel.quoteConversionRate")}
          tooltip={t("financial.tooltip.quoteConversionRate")}
          noComparisonCaption={t("financial.noComparison.quoteConversionRate")}
          loading={loading}
        />
      </div>
    </section>
  );
}
