"use client";

import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { AnalyticsCustomerRetention } from "@/lib/types";

type CustomerQuoteMetricsSectionProps = {
  customerRetention: AnalyticsCustomerRetention;
  quoteAcceptanceRatePercent: number | null;
  loading: boolean;
};

/** customer_retention is deliberately all-time (not window-scoped) and
 * quote_acceptance_rate_percent can be null for an organization with no
 * quotes yet -- both null cases get a translated explanation here, never
 * a silently-coerced 0%. */
export function CustomerQuoteMetricsSection({
  customerRetention,
  quoteAcceptanceRatePercent,
  loading,
}: CustomerQuoteMetricsSectionProps) {
  const { t } = useTranslation();

  return (
    <section aria-label={t("analytics.customersQuotesHeading")} className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight text-slate-900">
        {t("analytics.customersQuotesHeading")}
      </h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <DashboardCard
          title={t("analytics.totalInvoicedCustomersTitle")}
          value={String(customerRetention.total_invoiced_customers)}
          description={t("analytics.totalInvoicedCustomersDescription")}
          loading={loading}
        />
        <DashboardCard
          title={t("analytics.repeatCustomersTitle")}
          value={String(customerRetention.repeat_customers)}
          description={t("analytics.repeatCustomersDescription")}
          loading={loading}
        />
        <DashboardCard
          title={t("analytics.retentionRateTitle")}
          value={
            customerRetention.retention_rate_percent !== null
              ? `${customerRetention.retention_rate_percent.toFixed(1)}%`
              : t("analytics.notEnoughData")
          }
          description={t("analytics.retentionRateDescription")}
          loading={loading}
        />
        <DashboardCard
          title={t("analytics.quoteAcceptanceRateTitle")}
          value={
            quoteAcceptanceRatePercent !== null
              ? `${quoteAcceptanceRatePercent.toFixed(1)}%`
              : t("analytics.notEnoughData")
          }
          description={t("analytics.quoteAcceptanceRateDescription")}
          loading={loading}
        />
      </div>
    </section>
  );
}
