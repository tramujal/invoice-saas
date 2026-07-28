"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { CustomerQuoteMetricsSection } from "@/components/analytics/CustomerQuoteMetricsSection";
import { KpiSummaryCards } from "@/components/analytics/KpiSummaryCards";
import { RevenueBreakdownSection } from "@/components/analytics/RevenueBreakdownSection";
import { TimeWindowSelector } from "@/components/analytics/TimeWindowSelector";
import { PaymentStatusBreakdown } from "@/components/dashboard/PaymentStatusBreakdown";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import {
  ANALYTICS_TIME_WINDOWS,
  type AnalyticsTimeWindowKind,
  type KpiSnapshot,
} from "@/lib/types";

// Sentinel for the non-ApiError/non-403 catch branch, translated at render
// time rather than inside the callback -- same pattern as the dashboard
// and invoices pages (useTranslation()'s t is not identity-stable).
const GENERIC_LOAD_ERROR = "__generic_load_error__";
const PERMISSION_DENIED_ERROR = "__permission_denied__";

function isAnalyticsWindow(value: string | null): value is AnalyticsTimeWindowKind {
  return value !== null && (ANALYTICS_TIME_WINDOWS as string[]).includes(value);
}

function AnalyticsPageContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialWindow = isAnalyticsWindow(searchParams.get("window"))
    ? (searchParams.get("window") as AnalyticsTimeWindowKind)
    : "current_month";

  const [window_, setWindow] = useState<AnalyticsTimeWindowKind>(initialWindow);
  const [data, setData] = useState<KpiSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Cancels the in-flight request if the user switches windows again (or
  // navigates away) before the previous one resolves, instead of letting a
  // stale response overwrite a newer one.
  const abortRef = useRef<AbortController | null>(null);

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
      // Always a translated, generic message -- never the backend's own
      // response body, which is neither localized nor meant for display
      // (see e.g. average_payment_time.reason, an internal-facing string
      // by design, not end-user copy).
      if (e instanceof ApiError && e.status === 403) {
        setError(PERMISSION_DENIED_ERROR);
      } else {
        setError(GENERIC_LOAD_ERROR);
      }
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(window_);
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [window_]);

  function handleWindowChange(next: AnalyticsTimeWindowKind) {
    setWindow(next);
    const params = new URLSearchParams(searchParams.toString());
    params.set("window", next);
    router.replace(`/analytics?${params.toString()}`);
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

  return (
    <div className="mx-auto max-w-6xl space-y-8">
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
        actions={<TimeWindowSelector value={window_} onChange={handleWindowChange} />}
      />

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
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense fallback={null}>
      <AnalyticsPageContent />
    </Suspense>
  );
}
