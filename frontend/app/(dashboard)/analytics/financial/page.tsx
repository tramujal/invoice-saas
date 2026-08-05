"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CashCalendarSection } from "@/components/financial/CashCalendarSection";
import { CustomersSection } from "@/components/financial/CustomersSection";
import { ExecutiveKpisSection } from "@/components/financial/ExecutiveKpisSection";
import { AnomalyFlagsSection } from "@/components/financial/forecast/AnomalyFlagsSection";
import { ExpectedCollectionsSection } from "@/components/financial/forecast/ExpectedCollectionsSection";
import { ForecastAccuracySection } from "@/components/financial/forecast/ForecastAccuracySection";
import { ForecastConfidenceSection } from "@/components/financial/forecast/ForecastConfidenceSection";
import { ModelExplanationSection } from "@/components/financial/forecast/ModelExplanationSection";
import { ProjectionTableSection } from "@/components/financial/forecast/ProjectionTableSection";
import { RevenueForecastSection } from "@/components/financial/forecast/RevenueForecastSection";
import { ScenarioControlsSection } from "@/components/financial/forecast/ScenarioControlsSection";
import { ProductsSection } from "@/components/financial/ProductsSection";
import { QuotesFunnelSection } from "@/components/financial/QuotesFunnelSection";
import { ReceivablesAgingSection } from "@/components/financial/ReceivablesAgingSection";
import { RevenueTrendsSection } from "@/components/financial/RevenueTrendsSection";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { getCapabilityDeniedDetail } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type {
  AnomaliesResponse,
  CapabilityDeniedDetail,
  CashflowCalendarResponse,
  CollectionsForecastResponse,
  CustomersSectionResponse,
  ExecutiveOverviewResponse,
  ForecastAccuracyResponse,
  ForecastMethodsResponse,
  ForecastScenarioName,
  ForecastSummaryResponse,
  MonthlyProjectionResponse,
  ProductsSectionResponse,
  QuotesSectionResponse,
  ReceivablesAgingResponse,
  RevenueForecastResponse,
  RevenueTrendsResponse,
  ScenarioResponse,
} from "@/lib/types";

const SCENARIO_PRESETS: Record<
  ForecastScenarioName,
  { invoiceGrowthPercent: number; collectionDelayDays: number; quoteConversionDeltaPercent: number }
> = {
  base: { invoiceGrowthPercent: 0, collectionDelayDays: 0, quoteConversionDeltaPercent: 0 },
  optimistic: { invoiceGrowthPercent: 10, collectionDelayDays: -5, quoteConversionDeltaPercent: 10 },
  conservative: { invoiceGrowthPercent: -10, collectionDelayDays: 5, quoteConversionDeltaPercent: -10 },
};

const GENERIC_LOAD_ERROR = "__generic_load_error__";

/** Section 12 -- "avoid one giant endpoint / support partial loading":
 * each of these 7 sections is its own fetch, its own loading flag, and
 * fails independently -- one slow or erroring section never blocks the
 * others from rendering. The plan-capability gate is only checked once
 * (via the overview fetch); the other 6 only ever fire after it
 * succeeds, since they'd hit the identical 403 otherwise. */
export default function FinancialDashboardPage() {
  const { t } = useTranslation();

  const [capabilityDenied, setCapabilityDenied] = useState<CapabilityDeniedDetail | null>(null);
  const [gateChecked, setGateChecked] = useState(false);

  const [overview, setOverview] = useState<ExecutiveOverviewResponse | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [trends, setTrends] = useState<RevenueTrendsResponse | null>(null);
  const [trendsLoading, setTrendsLoading] = useState(true);

  const [aging, setAging] = useState<ReceivablesAgingResponse | null>(null);
  const [agingLoading, setAgingLoading] = useState(true);

  const [customers, setCustomers] = useState<CustomersSectionResponse | null>(null);
  const [customersLoading, setCustomersLoading] = useState(true);

  const [products, setProducts] = useState<ProductsSectionResponse | null>(null);
  const [productsLoading, setProductsLoading] = useState(true);

  const [quotes, setQuotes] = useState<QuotesSectionResponse | null>(null);
  const [quotesLoading, setQuotesLoading] = useState(true);

  const [calendar, setCalendar] = useState<CashflowCalendarResponse | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(true);
  const [calendarGranularity, setCalendarGranularity] = useState<"day" | "week" | "month">("week");

  // --- Phase 24.2 -- deterministic revenue forecasting ---------------------
  const [revenueForecast, setRevenueForecast] = useState<RevenueForecastResponse | null>(null);
  const [revenueForecastLoading, setRevenueForecastLoading] = useState(true);

  const [collectionsForecast, setCollectionsForecast] = useState<CollectionsForecastResponse | null>(null);
  const [collectionsForecastLoading, setCollectionsForecastLoading] = useState(true);

  const [monthlyProjection, setMonthlyProjection] = useState<MonthlyProjectionResponse | null>(null);
  const [monthlyProjectionLoading, setMonthlyProjectionLoading] = useState(true);

  const [forecastSummary, setForecastSummary] = useState<ForecastSummaryResponse | null>(null);
  const [forecastSummaryLoading, setForecastSummaryLoading] = useState(true);

  const [forecastAccuracy, setForecastAccuracy] = useState<ForecastAccuracyResponse | null>(null);
  const [forecastAccuracyLoading, setForecastAccuracyLoading] = useState(true);

  const [forecastMethods, setForecastMethods] = useState<ForecastMethodsResponse | null>(null);
  const [forecastMethodsLoading, setForecastMethodsLoading] = useState(true);

  const [anomalies, setAnomalies] = useState<AnomaliesResponse | null>(null);
  const [anomaliesLoading, setAnomaliesLoading] = useState(true);

  const [scenario, setScenario] = useState<ForecastScenarioName>("base");
  const [invoiceGrowthPercent, setInvoiceGrowthPercent] = useState(0);
  const [collectionDelayDays, setCollectionDelayDays] = useState(0);
  const [quoteConversionDeltaPercent, setQuoteConversionDeltaPercent] = useState(0);
  const [scenarioResult, setScenarioResult] = useState<ScenarioResponse | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(true);

  const forecastPlanRestricted = revenueForecast?.plan_restricted ?? false;

  const handleScenarioChange = useCallback((next: ForecastScenarioName) => {
    setScenario(next);
    const preset = SCENARIO_PRESETS[next];
    setInvoiceGrowthPercent(preset.invoiceGrowthPercent);
    setCollectionDelayDays(preset.collectionDelayDays);
    setQuoteConversionDeltaPercent(preset.quoteConversionDeltaPercent);
  }, []);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const loadOverview = useCallback(async () => {
    setOverviewLoading(true);
    setOverviewError(null);
    try {
      const data = await apiFetch<ExecutiveOverviewResponse>(orgPath("financial-intelligence/overview"));
      if (!mountedRef.current) return;
      setOverview(data);
      setGateChecked(true);
    } catch (e) {
      if (!mountedRef.current) return;
      const detail = getCapabilityDeniedDetail(e);
      if (detail) {
        setCapabilityDenied(detail);
      } else {
        setOverviewError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
      }
      setGateChecked(true);
    } finally {
      if (mountedRef.current) setOverviewLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  // Fires the other 5 independent section fetches (cash calendar is its
  // own effect below, since it alone has a user-adjustable query param)
  // only once the plan gate is confirmed open -- each still fails/loads
  // independently of the others from this point on.
  useEffect(() => {
    if (!gateChecked || capabilityDenied) return;

    setTrendsLoading(true);
    apiFetch<RevenueTrendsResponse>(orgPath("financial-intelligence/revenue-trends"))
      .then((data) => mountedRef.current && setTrends(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setTrendsLoading(false));

    setAgingLoading(true);
    apiFetch<ReceivablesAgingResponse>(orgPath("financial-intelligence/receivables-aging"))
      .then((data) => mountedRef.current && setAging(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setAgingLoading(false));

    setCustomersLoading(true);
    apiFetch<CustomersSectionResponse>(orgPath("financial-intelligence/customers"))
      .then((data) => mountedRef.current && setCustomers(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setCustomersLoading(false));

    setProductsLoading(true);
    apiFetch<ProductsSectionResponse>(orgPath("financial-intelligence/products"))
      .then((data) => mountedRef.current && setProducts(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setProductsLoading(false));

    setRevenueForecastLoading(true);
    apiFetch<RevenueForecastResponse>(orgPath("financial-intelligence/forecast/revenue"))
      .then((data) => mountedRef.current && setRevenueForecast(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setRevenueForecastLoading(false));

    setCollectionsForecastLoading(true);
    apiFetch<CollectionsForecastResponse>(orgPath("financial-intelligence/forecast/collections"))
      .then((data) => mountedRef.current && setCollectionsForecast(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setCollectionsForecastLoading(false));

    setMonthlyProjectionLoading(true);
    apiFetch<MonthlyProjectionResponse>(orgPath("financial-intelligence/forecast/monthly-projection"))
      .then((data) => mountedRef.current && setMonthlyProjection(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setMonthlyProjectionLoading(false));

    setForecastSummaryLoading(true);
    apiFetch<ForecastSummaryResponse>(orgPath("financial-intelligence/forecast/summary"))
      .then((data) => mountedRef.current && setForecastSummary(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setForecastSummaryLoading(false));

    setForecastAccuracyLoading(true);
    apiFetch<ForecastAccuracyResponse>(orgPath("financial-intelligence/forecast/accuracy"))
      .then((data) => mountedRef.current && setForecastAccuracy(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setForecastAccuracyLoading(false));

    setForecastMethodsLoading(true);
    apiFetch<ForecastMethodsResponse>(orgPath("financial-intelligence/forecast/methods"))
      .then((data) => mountedRef.current && setForecastMethods(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setForecastMethodsLoading(false));

    setAnomaliesLoading(true);
    apiFetch<AnomaliesResponse>(orgPath("financial-intelligence/forecast/anomalies"))
      .then((data) => mountedRef.current && setAnomalies(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setAnomaliesLoading(false));

    setQuotesLoading(true);
    apiFetch<QuotesSectionResponse>(orgPath("financial-intelligence/quotes"))
      .then((data) => mountedRef.current && setQuotes(data))
      .catch(() => undefined)
      .finally(() => mountedRef.current && setQuotesLoading(false));
  }, [gateChecked, capabilityDenied]);

  // The cash calendar's own granularity control re-fetches on change --
  // kept separate from the batch above since it's the only section with
  // a user-adjustable query parameter.
  useEffect(() => {
    if (!gateChecked || capabilityDenied) return;
    setCalendarLoading(true);
    apiFetch<CashflowCalendarResponse>(
      orgPath(`financial-intelligence/cashflow-calendar?granularity=${calendarGranularity}`)
    )
      .then((data) => {
        if (mountedRef.current) setCalendar(data);
      })
      .catch(() => undefined)
      .finally(() => {
        if (mountedRef.current) setCalendarLoading(false);
      });
  }, [gateChecked, capabilityDenied, calendarGranularity]);

  // Scenario controls: re-POSTs whenever the scenario preset or any
  // assumption input changes, debounced slightly so typing in a number
  // input doesn't fire a request per keystroke. Never mutates stored
  // business data server-side (see evaluate_scenario's own docstring) --
  // purely a recomputation of the same deterministic forecast.
  useEffect(() => {
    if (!gateChecked || capabilityDenied) return;
    const timeout = setTimeout(() => {
      setScenarioLoading(true);
      apiFetch<ScenarioResponse>(orgPath("financial-intelligence/forecast/scenario"), {
        method: "POST",
        body: JSON.stringify({
          scenario,
          assumptions: {
            invoice_growth_percent: invoiceGrowthPercent,
            collection_delay_days: collectionDelayDays,
            quote_conversion_delta_percent: quoteConversionDeltaPercent,
          },
        }),
      })
        .then((data) => mountedRef.current && setScenarioResult(data))
        .catch(() => undefined)
        .finally(() => mountedRef.current && setScenarioLoading(false));
    }, 300);
    return () => clearTimeout(timeout);
  }, [
    gateChecked,
    capabilityDenied,
    scenario,
    invoiceGrowthPercent,
    collectionDelayDays,
    quoteConversionDeltaPercent,
  ]);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        title={t("financial.title")}
        subtitle={t("financial.subtitle")}
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
            <path d="m19 9-5 5-4-4-3 3" />
          </svg>
        }
        actions={<Badge className="bg-slate-100 text-slate-600 ring-slate-200">{t("financial.deterministicBadge")}</Badge>}
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
          title={t("financial.planRestrictedTitle")}
          description={t("financial.planRestrictedDescription", { plan: capabilityDenied.plan.name })}
        />
      ) : (
        <>
          {overviewError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
              {overviewError === GENERIC_LOAD_ERROR ? t("financial.loadError") : overviewError}
            </div>
          ) : null}

          <ExecutiveKpisSection overview={overview} loading={overviewLoading} />
          <RevenueTrendsSection trends={trends} loading={trendsLoading} />
          <ReceivablesAgingSection aging={aging} loading={agingLoading} />
          <CustomersSection data={customers} loading={customersLoading} />
          <ProductsSection data={products} loading={productsLoading} />
          <QuotesFunnelSection data={quotes} loading={quotesLoading} />
          <CashCalendarSection
            data={calendar}
            loading={calendarLoading}
            granularity={calendarGranularity}
            onGranularityChange={setCalendarGranularity}
          />

          {/* Phase 24.2 -- deterministic revenue forecasting. Every section
              below reads its OWN `plan_restricted` flag from its response
              (a soft gate, unlike the hard 403 above) rather than relying
              on `capabilityDenied`, which only ever reflects the Phase
              24.1 dashboard's advanced_financial_analytics capability. */}
          <ForecastConfidenceSection
            data={forecastSummary}
            loading={forecastSummaryLoading}
            planRestricted={forecastPlanRestricted}
          />
          <RevenueForecastSection
            forecast={revenueForecast}
            monthlyProjection={monthlyProjection}
            trends={trends}
            loading={revenueForecastLoading}
            planRestricted={forecastPlanRestricted}
          />
          <ExpectedCollectionsSection
            data={collectionsForecast}
            loading={collectionsForecastLoading}
            planRestricted={forecastPlanRestricted}
          />
          <ScenarioControlsSection
            scenario={scenario}
            onScenarioChange={handleScenarioChange}
            invoiceGrowthPercent={invoiceGrowthPercent}
            onInvoiceGrowthPercentChange={setInvoiceGrowthPercent}
            collectionDelayDays={collectionDelayDays}
            onCollectionDelayDaysChange={setCollectionDelayDays}
            quoteConversionDeltaPercent={quoteConversionDeltaPercent}
            onQuoteConversionDeltaPercentChange={setQuoteConversionDeltaPercent}
            data={scenarioResult}
            loading={scenarioLoading}
            planRestricted={forecastPlanRestricted}
          />
          <ModelExplanationSection
            methods={forecastMethods}
            accuracy={forecastAccuracy}
            loading={forecastMethodsLoading || forecastAccuracyLoading}
            planRestricted={forecastPlanRestricted}
          />
          <ForecastAccuracySection
            data={forecastAccuracy}
            loading={forecastAccuracyLoading}
            planRestricted={forecastPlanRestricted}
          />
          <ProjectionTableSection
            data={monthlyProjection}
            loading={monthlyProjectionLoading}
            planRestricted={forecastPlanRestricted}
          />
          <AnomalyFlagsSection data={anomalies} loading={anomaliesLoading} planRestricted={forecastPlanRestricted} />
        </>
      )}
    </div>
  );
}
