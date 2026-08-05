"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CashCalendarSection } from "@/components/financial/CashCalendarSection";
import { CustomersSection } from "@/components/financial/CustomersSection";
import { ExecutiveKpisSection } from "@/components/financial/ExecutiveKpisSection";
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
  CapabilityDeniedDetail,
  CashflowCalendarResponse,
  CustomersSectionResponse,
  ExecutiveOverviewResponse,
  ProductsSectionResponse,
  QuotesSectionResponse,
  ReceivablesAgingResponse,
  RevenueTrendsResponse,
} from "@/lib/types";

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
        </>
      )}
    </div>
  );
}
