"use client";

import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { AnalyticsAveragePaymentTime } from "@/lib/types";

type KpiSummaryCardsProps = {
  totalInvoices: number;
  customerGrowth: number;
  averagePaymentTime: AnalyticsAveragePaymentTime;
  loading: boolean;
};

/** The currency-agnostic "at a glance" numbers -- every figure here is a
 * plain count or a day count, never a monetary amount, so it never runs
 * into the multi-currency "don't sum across currencies" problem that the
 * revenue section has to solve. */
export function KpiSummaryCards({
  totalInvoices,
  customerGrowth,
  averagePaymentTime,
  loading,
}: KpiSummaryCardsProps) {
  const { t } = useTranslation();

  const growthPrefix = customerGrowth > 0 ? "+" : "";

  return (
    <section
      aria-label={t("analytics.summaryAriaLabel")}
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
    >
      <DashboardCard
        title={t("analytics.totalInvoicesTitle")}
        value={String(totalInvoices)}
        description={t("analytics.totalInvoicesDescription")}
        loading={loading}
        tone="info"
      />
      <DashboardCard
        title={t("analytics.customerGrowthTitle")}
        value={`${growthPrefix}${customerGrowth}`}
        description={t("analytics.customerGrowthDescription")}
        loading={loading}
        tone={customerGrowth > 0 ? "success" : "neutral"}
      />
      <DashboardCard
        title={t("analytics.averagePaymentTimeTitle")}
        value={
          averagePaymentTime.available && averagePaymentTime.average_days !== null
            ? t("analytics.averagePaymentTimeValue", {
                days: averagePaymentTime.average_days.toFixed(1),
              })
            : t("analytics.averagePaymentTimeUnavailable")
        }
        description={t("analytics.averagePaymentTimeDescription")}
        loading={loading}
        tone="neutral"
      />
    </section>
  );
}
