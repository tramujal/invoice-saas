"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { ComparisonPeriodSelector } from "@/components/analytics/ComparisonPeriodSelector";
import { CustomerQuoteMetricsSection } from "@/components/analytics/CustomerQuoteMetricsSection";
import { ForecastCard } from "@/components/analytics/ForecastCard";
import { KpiSummaryCards } from "@/components/analytics/KpiSummaryCards";
import { MonthlyEvolutionChart } from "@/components/analytics/MonthlyEvolutionChart";
import { PeriodComparisonCards } from "@/components/analytics/PeriodComparisonCards";
import { RevenueBreakdownSection } from "@/components/analytics/RevenueBreakdownSection";
import { TimeWindowSelector } from "@/components/analytics/TimeWindowSelector";
import { CurrencySelector } from "@/components/dashboard/CurrencySelector";
import { PaymentStatusBreakdown } from "@/components/dashboard/PaymentStatusBreakdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { getCapabilityDeniedDetail } from "@/lib/format-api-error";
import { formatMoney } from "@/lib/money";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  ANALYTICS_TIME_WINDOWS,
  COMPARISON_PERIOD_KINDS,
  type AnalyticsTimeWindowKind,
  type CapabilityDeniedDetail,
  type ComparisonPeriodKind,
  type Forecast,
  type KpiSnapshot,
  type SeriesPoint,
  type TrendSnapshot,
} from "@/lib/types";

// Sentinel for the non-ApiError/non-403 catch branch, translated at render
// time rather than inside the callback -- same pattern as the dashboard
// and invoices pages (useTranslation()'s t is not identity-stable).
const GENERIC_LOAD_ERROR = "__generic_load_error__";
const PERMISSION_DENIED_ERROR = "__permission_denied__";

const EMPTY_FORECAST: Forecast = {
  available: false,
  method: null,
  forecast_value: null,
  inputs: [],
  window_size: null,
  reason: null,
};

function isAnalyticsWindow(value: string | null): value is AnalyticsTimeWindowKind {
  return value !== null && (ANALYTICS_TIME_WINDOWS as string[]).includes(value);
}

function isComparisonKind(value: string | null): value is ComparisonPeriodKind {
  return value !== null && (COMPARISON_PERIOD_KINDS as string[]).includes(value);
}

function countSeriesToNumberFormatter(value: number): string {
  return String(Math.round(value));
}

function AnalyticsPageContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialWindow = isAnalyticsWindow(searchParams.get("window"))
    ? (searchParams.get("window") as AnalyticsTimeWindowKind)
    : "current_month";
  const initialComparison = isComparisonKind(searchParams.get("comparison"))
    ? (searchParams.get("comparison") as ComparisonPeriodKind)
    : "current_month";

  const [window_, setWindow] = useState<AnalyticsTimeWindowKind>(initialWindow);
  const [data, setData] = useState<KpiSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Set when the backend returns 403 feature_not_available (see
  // app.billing.enforcement.require_analytics) -- distinct from a plain
  // 403 (role-based PERMISSION_DENIED_ERROR), since the fix here is
  // upgrading the plan, not asking an admin for a permission. Takes over
  // the whole page instead of just the KPI/trend sections, since neither
  // endpoint returns any usable data once analytics isn't entitled.
  const [capabilityDenied, setCapabilityDenied] = useState<CapabilityDeniedDetail | null>(null);

  const [comparison, setComparison] = useState<ComparisonPeriodKind>(initialComparison);
  const [trendData, setTrendData] = useState<TrendSnapshot | null>(null);
  const [trendLoading, setTrendLoading] = useState(true);
  const [trendError, setTrendError] = useState<string | null>(null);
  const [trendCurrency, setTrendCurrency] = useState<string | null>(null);

  // Cancels the in-flight request if the user switches windows again (or
  // navigates away) before the previous one resolves, instead of letting a
  // stale response overwrite a newer one.
  const abortRef = useRef<AbortController | null>(null);
  const trendAbortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (kind: AnalyticsTimeWindowKind) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const snapshot = await apiFetch<KpiSnapshot>(
        orgPath(`analytics/kpis?window=${kind}`),
        { signal: controller.signal }
      );
      setData(snapshot);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      const capabilityDetail = getCapabilityDeniedDetail(e);
      // Always a translated, generic message -- never the backend's own
      // response body, which is neither localized nor meant for display
      // (see e.g. average_payment_time.reason, an internal-facing string
      // by design, not end-user copy).
      if (capabilityDetail) {
        setCapabilityDenied(capabilityDetail);
      } else if (e instanceof ApiError && e.status === 403) {
        setError(PERMISSION_DENIED_ERROR);
      } else {
        setError(GENERIC_LOAD_ERROR);
      }
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, []);

  const loadTrends = useCallback(async (kind: ComparisonPeriodKind) => {
    trendAbortRef.current?.abort();
    const controller = new AbortController();
    trendAbortRef.current = controller;
    setTrendLoading(true);
    setTrendError(null);
    try {
      const snapshot = await apiFetch<TrendSnapshot>(
        orgPath(`analytics/trends?comparison=${kind}&granularity=monthly`),
        { signal: controller.signal }
      );
      setTrendData(snapshot);
      setTrendCurrency((current) => {
        const currencies = Object.keys(snapshot.revenue_trend).sort();
        if (current && currencies.includes(current)) return current;
        return currencies[0] ?? null;
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      const capabilityDetail = getCapabilityDeniedDetail(e);
      if (capabilityDetail) {
        setCapabilityDenied(capabilityDetail);
      } else if (e instanceof ApiError && e.status === 403) {
        setTrendError(PERMISSION_DENIED_ERROR);
      } else {
        setTrendError(GENERIC_LOAD_ERROR);
      }
    } finally {
      if (trendAbortRef.current === controller) setTrendLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(window_);
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window_]);

  useEffect(() => {
    void loadTrends(comparison);
    return () => trendAbortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [comparison]);

  function updateQuery(next: Record<string, string>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(next)) params.set(key, value);
    router.replace(`/analytics?${params.toString()}`);
  }

  function handleWindowChange(next: AnalyticsTimeWindowKind) {
    setWindow(next);
    updateQuery({ window: next });
  }

  function handleComparisonChange(next: ComparisonPeriodKind) {
    setComparison(next);
    updateQuery({ comparison: next });
  }

  const invoiceCounts = data?.invoice_counts ?? { total: 0, pending: 0, paid: 0, overdue: 0 };
  const averagePaymentTime = data?.average_payment_time ?? {
    available: false,
    average_days: null,
    reason: null,
  };
  const customerRetention = data?.customer_retention ?? {
    total_invoiced_customers: 0,
    repeat_customers: 0,
    retention_rate_percent: null,
  };

  const revenueTrend = trendData?.revenue_trend ?? {};
  const trendCurrencies = Object.keys(revenueTrend).sort();
  const effectiveTrendCurrency = trendCurrency ?? trendCurrencies[0] ?? null;
  const revenueSeriesForCurrency: SeriesPoint[] = effectiveTrendCurrency
    ? (trendData?.revenue_series ?? []).filter((p) => p.currency_code === effectiveTrendCurrency)
    : [];
  const revenueForecastForCurrency: Forecast = effectiveTrendCurrency
    ? trendData?.revenue_forecast[effectiveTrendCurrency] ?? EMPTY_FORECAST
    : EMPTY_FORECAST;

  return (
    <PageContainer spacing="8">
      <PageHeader
        title={t("analytics.title")}
        subtitle={
          data
            ? t("analytics.rangeSubtitle", {
                start: new Date(data.window.start).toLocaleDateString(),
                end: new Date(data.window.end).toLocaleDateString(),
              })
            : t("analytics.subtitle")
        }
        icon={
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M3 3v18h18" />
            <path d="M18 17V9" />
            <path d="M13 17V5" />
            <path d="M8 17v-3" />
          </svg>
        }
        actions={capabilityDenied ? undefined : <TimeWindowSelector value={window_} onChange={handleWindowChange} />}
      />

      {capabilityDenied ? (
        <EmptyState
          icon={
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <rect x="3" y="11" width="18" height="10" rx="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          }
          title={t("analytics.planRestrictedTitle")}
          description={t("analytics.planRestrictedDescription", { plan: capabilityDenied.plan.name })}
        />
      ) : (
        <>
          {error ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error === GENERIC_LOAD_ERROR
            ? t("analytics.loadError")
            : error === PERMISSION_DENIED_ERROR
              ? t("analytics.permissionDenied")
              : error}
        </div>
      ) : null}

      <KpiSummaryCards
        totalInvoices={invoiceCounts.total}
        customerGrowth={data?.customer_growth ?? 0}
        averagePaymentTime={averagePaymentTime}
        loading={loading}
      />

      <section aria-label={t("analytics.invoiceStatusHeading")} className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("analytics.invoiceStatusHeading")}
        </h2>
        <PaymentStatusBreakdown
          pending={invoiceCounts.pending}
          paid={invoiceCounts.paid}
          overdue={invoiceCounts.overdue}
          loading={loading}
        />
      </section>

      <RevenueBreakdownSection
        revenueBreakdown={data?.revenue_breakdown ?? []}
        averageInvoiceValue={data?.average_invoice_value ?? {}}
        loading={loading}
      />

      <CustomerQuoteMetricsSection
        customerRetention={customerRetention}
        quoteAcceptanceRatePercent={data?.quote_acceptance_rate_percent ?? null}
        loading={loading}
      />

      {/* --- Phase 16C: trend analysis & forecasting ------------------- */}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-8">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("analytics.comparisonHeading")}
        </h2>
        <ComparisonPeriodSelector value={comparison} onChange={handleComparisonChange} />
      </div>

      {trendError ? (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {trendError === GENERIC_LOAD_ERROR
            ? t("analytics.loadError")
            : t("analytics.permissionDenied")}
        </div>
      ) : null}

      <PeriodComparisonCards
        revenueTrend={revenueTrend}
        invoiceCountTrend={
          trendData?.invoice_count_trend ?? {
            current: "0.00",
            previous: "0.00",
            absolute_difference: "0.00",
            percentage_difference: null,
            direction: "unknown",
          }
        }
        customerGrowthTrend={
          trendData?.customer_growth_trend ?? {
            current: "0.00",
            previous: "0.00",
            absolute_difference: "0.00",
            percentage_difference: null,
            direction: "unknown",
          }
        }
        quoteCountTrend={
          trendData?.quote_count_trend ?? {
            current: "0.00",
            previous: "0.00",
            absolute_difference: "0.00",
            percentage_difference: null,
            direction: "unknown",
          }
        }
        loading={trendLoading}
      />

      <section aria-label={t("analytics.evolutionHeading")} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">
            {t("analytics.evolutionHeading")}
          </h2>
          {trendCurrencies.length > 1 && effectiveTrendCurrency ? (
            <CurrencySelector
              currencies={trendCurrencies}
              selected={effectiveTrendCurrency}
              onSelect={setTrendCurrency}
              t={t}
            />
          ) : null}
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <MonthlyEvolutionChart
            title={
              effectiveTrendCurrency
                ? t("analytics.evolutionRevenueTitle", { currency: effectiveTrendCurrency })
                : t("analytics.evolutionRevenueTitleGeneric")
            }
            data={revenueSeriesForCurrency}
            granularity={trendData?.granularity ?? "monthly"}
            emptyMessage={t("analytics.evolutionEmpty")}
            loading={trendLoading}
            valueName={t("dashboard.revenueLabel")}
            formatValue={formatMoney}
          />
          <MonthlyEvolutionChart
            title={t("analytics.evolutionInvoiceCountTitle")}
            data={trendData?.invoice_count_series ?? []}
            granularity={trendData?.granularity ?? "monthly"}
            emptyMessage={t("analytics.evolutionEmpty")}
            loading={trendLoading}
            valueName={t("nav.invoices")}
            formatValue={countSeriesToNumberFormatter}
          />
          <MonthlyEvolutionChart
            title={t("analytics.evolutionCustomerCountTitle")}
            data={trendData?.customer_count_series ?? []}
            granularity={trendData?.granularity ?? "monthly"}
            emptyMessage={t("analytics.evolutionEmpty")}
            loading={trendLoading}
            valueName={t("nav.customers")}
            formatValue={countSeriesToNumberFormatter}
          />
          <MonthlyEvolutionChart
            title={t("analytics.evolutionQuoteConversionTitle")}
            data={trendData?.quote_conversion_series ?? []}
            granularity={trendData?.granularity ?? "monthly"}
            emptyMessage={t("analytics.evolutionEmpty")}
            loading={trendLoading}
            valueName={t("nav.quotes")}
            formatValue={countSeriesToNumberFormatter}
          />
        </div>
      </section>

      <section aria-label={t("analytics.forecastHeading")} className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {t("analytics.forecastHeading")}
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ForecastCard
            title={
              effectiveTrendCurrency
                ? t("analytics.forecastRevenueTitle", { currency: effectiveTrendCurrency })
                : t("analytics.evolutionRevenueTitleGeneric")
            }
            forecast={revenueForecastForCurrency}
            loading={trendLoading}
            formatValue={(value) => formatMoney(Number.parseFloat(value))}
          />
          <ForecastCard
            title={t("analytics.forecastInvoiceCountTitle")}
            forecast={trendData?.invoice_count_forecast ?? EMPTY_FORECAST}
            loading={trendLoading}
            formatValue={(value) => countSeriesToNumberFormatter(Number.parseFloat(value))}
          />
        </div>
      </section>
        </>
      )}
    </PageContainer>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense fallback={null}>
      <AnalyticsPageContent />
    </Suspense>
  );
}
