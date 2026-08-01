"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DailySignupsChart } from "@/components/admin/DailySignupsChart";
import { FeatureAdoptionChart } from "@/components/admin/FeatureAdoptionChart";
import { OrganizationSplitChart } from "@/components/admin/OrganizationSplitChart";
import { UsageOutcomeChart } from "@/components/admin/UsageOutcomeChart";
import { WeeklyActiveOrganizationsChart } from "@/components/admin/WeeklyActiveOrganizationsChart";
import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import type {
  PlatformBusinessMetrics,
  PlatformDashboard,
  PlatformGrowthMetrics,
  PlatformSystemHealth,
  PlatformUsageMetrics,
} from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

/** Generic per-section load state -- Phase 21's four sections each fetch
 * independently (see useSectionLoader below) so one section's failure
 * never blanks out the others, matching this page's own existing
 * error-banner precedent for the legacy overview data. */
function useSectionLoader<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const json = await apiFetch<T>(path, { signal: controller.signal });
      setData(json);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  return { data, loading, error, reload: load };
}

export default function PlatformAdminDashboardPage() {
  const { t } = useTranslation();

  const overview = useSectionLoader<PlatformDashboard>("/admin/dashboard");
  const business = useSectionLoader<PlatformBusinessMetrics>("/admin/dashboard/business");
  const usage = useSectionLoader<PlatformUsageMetrics>("/admin/dashboard/usage");
  const health = useSectionLoader<PlatformSystemHealth>("/admin/system/health");
  const growth = useSectionLoader<PlatformGrowthMetrics>("/admin/dashboard/growth?days=30");

  function reloadAll() {
    void overview.reload();
    void business.reload();
    void usage.reload();
    void health.reload();
    void growth.reload();
  }

  const anyLoading = overview.loading || business.loading || usage.loading || health.loading || growth.loading;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        title={t("admin.dashboardTitle")}
        subtitle={t("admin.dashboardSubtitle")}
        actions={
          <Button type="button" variant="secondary" size="sm" onClick={reloadAll} loading={anyLoading}>
            {anyLoading ? t("common.refreshing") : t("common.refresh")}
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <DashboardCard
          title={t("admin.organizationsTotal")}
          value={overview.data ? String(overview.data.organizations_total) : "—"}
          description={
            overview.data
              ? t("admin.new7d30d", { d7: overview.data.organizations_new_7d, d30: overview.data.organizations_new_30d })
              : undefined
          }
          loading={overview.loading}
          href="/admin/organizations"
        />
        <DashboardCard
          title={t("admin.usersTotal")}
          value={overview.data ? String(overview.data.users_total) : "—"}
          description={
            overview.data ? t("admin.new7d30d", { d7: overview.data.users_new_7d, d30: overview.data.users_new_30d }) : undefined
          }
          loading={overview.loading}
          href="/admin/users"
        />
        <DashboardCard title={t("admin.invoicesTotal")} value={overview.data ? String(overview.data.invoices_total) : "—"} loading={overview.loading} />
        <DashboardCard title={t("admin.quotesTotal")} value={overview.data ? String(overview.data.quotes_total) : "—"} loading={overview.loading} />
        <DashboardCard title={t("admin.customersTotal")} value={overview.data ? String(overview.data.customers_total) : "—"} loading={overview.loading} />
        <DashboardCard title={t("admin.productsTotal")} value={overview.data ? String(overview.data.products_total) : "—"} loading={overview.loading} />
        <DashboardCard
          title={t("admin.reminderEmails7d")}
          value={overview.data ? String(overview.data.reminder_emails_sent_7d) : "—"}
          description={overview.data ? t("admin.reminderEmailsFailed7d", { count: overview.data.reminder_emails_failed_7d }) : undefined}
          loading={overview.loading}
        />
        <DashboardCard title={t("admin.aiActionsExecuted7d")} value={overview.data ? String(overview.data.ai_actions_executed_7d) : "—"} loading={overview.loading} />
      </div>

      {/* ---------- Business Metrics ---------- */}
      <section aria-label={t("opsDashboard.businessSectionTitle")} className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-900">{t("opsDashboard.businessSectionTitle")}</h2>
        {business.error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {business.error === GENERIC_LOAD_ERROR ? t("opsDashboard.loadError") : business.error}
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Phase UX4: a $0 MRR/ARR in a green card reads as "this is
              good news," which is misleading for an org with no paying
              customers yet -- green is earned by an actual positive
              value, not just by being a revenue metric. */}
          <DashboardCard
            title={t("opsDashboard.mrr")}
            value={business.data ? formatCurrency(business.data.mrr, business.data.currency) : "—"}
            loading={business.loading}
            tone={business.data && Number.parseFloat(business.data.mrr) > 0 ? "success" : "neutral"}
          />
          <DashboardCard
            title={t("opsDashboard.arr")}
            value={business.data ? formatCurrency(business.data.arr, business.data.currency) : "—"}
            loading={business.loading}
            tone={business.data && Number.parseFloat(business.data.arr) > 0 ? "success" : "neutral"}
          />
          <DashboardCard
            title={t("opsDashboard.payingOrganizations")}
            value={business.data ? String(business.data.paying_organizations) : "—"}
            loading={business.loading}
            href="/admin/subscriptions"
          />
          <DashboardCard
            title={t("opsDashboard.trialOrganizations")}
            value={business.data ? String(business.data.trial_organizations) : "—"}
            loading={business.loading}
            href="/admin/subscriptions"
          />
          <DashboardCard title={t("opsDashboard.activeUsers")} value={business.data ? String(business.data.active_users_total) : "—"} loading={business.loading} />
          <DashboardCard title={t("opsDashboard.churnRate")} value={business.data ? `${business.data.churn_rate_30d}%` : "—"} loading={business.loading} />
          <DashboardCard title={t("opsDashboard.conversionRate")} value={business.data ? `${business.data.conversion_rate_30d}%` : "—"} loading={business.loading} />
          <DashboardCard title={t("opsDashboard.arpu")} value={business.data ? formatCurrency(business.data.average_revenue_per_organization, business.data.currency) : "—"} loading={business.loading} />
        </div>
        <OrganizationSplitChart data={business.data} loading={business.loading} />
      </section>

      {/* ---------- Usage Metrics ---------- */}
      <section aria-label={t("opsDashboard.usageSectionTitle")} className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-900">{t("opsDashboard.usageSectionTitle")}</h2>
        {usage.error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {usage.error === GENERIC_LOAD_ERROR ? t("opsDashboard.loadError") : usage.error}
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <DashboardCard title={t("opsDashboard.aiRequests")} value={usage.data ? String(usage.data.ai_requests_30d) : "—"} loading={usage.loading} />
          <DashboardCard
            title={t("opsDashboard.apiKeys")}
            value={usage.data ? String(usage.data.api_keys_active) : "—"}
            description={usage.data ? t("opsDashboard.apiKeysUsed7d", { count: usage.data.api_keys_used_7d }) : undefined}
            loading={usage.loading}
          />
          <DashboardCard title={t("opsDashboard.webhookDeliveries")} value={usage.data ? String(usage.data.webhook_deliveries_30d) : "—"} loading={usage.loading} />
          <DashboardCard title={t("opsDashboard.backgroundJobs")} value={usage.data ? String(usage.data.background_jobs_30d) : "—"} loading={usage.loading} href="/admin/jobs" />
          <DashboardCard title={t("opsDashboard.emailsSent")} value={usage.data ? String(usage.data.emails_sent_30d) : "—"} loading={usage.loading} />
          <DashboardCard title={t("opsDashboard.notificationsCreated")} value={usage.data ? String(usage.data.notifications_created_30d) : "—"} loading={usage.loading} />
        </div>
        <UsageOutcomeChart data={usage.data} loading={usage.loading} />
      </section>

      {/* ---------- System Health ---------- */}
      <section aria-label={t("admin.systemHealthTitle")} className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-900">{t("admin.systemHealthTitle")}</h2>
        {health.error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {health.error === GENERIC_LOAD_ERROR ? t("opsDashboard.loadError") : health.error}
          </div>
        ) : null}
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div className="flex flex-wrap gap-2">
            <HealthPill label={t("admin.databaseLabel")} ok={health.data?.database_reachable ?? null} loading={health.loading} />
            <HealthPill label={t("admin.emailProviderLabel")} ok={health.data ? health.data.email_provider_configured : null} loading={health.loading} />
            <HealthPill label={t("admin.aiProviderLabel")} ok={health.data ? health.data.ai_provider_configured : null} loading={health.loading} />
          </div>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <DashboardCard title={t("opsDashboard.queuePending")} value={health.data ? String(health.data.queue_pending) : "—"} loading={health.loading} href="/admin/jobs" />
          <DashboardCard title={t("opsDashboard.queueRunning")} value={health.data ? String(health.data.queue_running) : "—"} loading={health.loading} href="/admin/jobs" />
          <DashboardCard title={t("opsDashboard.jobsFailed")} value={health.data ? String(health.data.jobs_failed_total) : "—"} loading={health.loading} tone={health.data && health.data.jobs_failed_total > 0 ? "danger" : "neutral"} href="/admin/jobs" />
          <DashboardCard title={t("opsDashboard.retryScheduled")} value={health.data ? String(health.data.queue_retry_scheduled) : "—"} loading={health.loading} href="/admin/jobs" />
          <DashboardCard title={t("opsDashboard.storageUsed")} value={health.data ? `${health.data.storage_used_mb} MB` : "—"} loading={health.loading} />
          <DashboardCard title={t("opsDashboard.databaseSize")} value={health.data?.database_size_mb != null ? `${health.data.database_size_mb} MB` : t("opsDashboard.unavailable")} loading={health.loading} />
          <DashboardCard
            title={t("opsDashboard.averageApiLatency")}
            value={health.data?.average_api_latency_ms != null ? `${health.data.average_api_latency_ms} ms` : t("opsDashboard.unavailable")}
            description={health.data ? t("opsDashboard.requestSampleCount", { count: health.data.request_sample_count }) : undefined}
            loading={health.loading}
          />
          <DashboardCard title={t("opsDashboard.errorRate")} value={health.data?.error_rate_percent != null ? `${health.data.error_rate_percent}%` : t("opsDashboard.unavailable")} loading={health.loading} />
        </div>
      </section>

      {/* ---------- Growth ---------- */}
      <section aria-label={t("opsDashboard.growthSectionTitle")} className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-900">{t("opsDashboard.growthSectionTitle")}</h2>
        {growth.error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {growth.error === GENERIC_LOAD_ERROR ? t("opsDashboard.loadError") : growth.error}
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {/* Phase UX4: this one genuinely is a trend (can go negative),
              unlike MRR/ARR above -- green for growth, red for decline,
              neutral only at exactly 0. */}
          <DashboardCard
            title={t("opsDashboard.monthlyGrowth")}
            value={growth.data ? `${growth.data.monthly_growth_percent}%` : "—"}
            loading={growth.loading}
            tone={
              !growth.data || growth.data.monthly_growth_percent === 0
                ? "neutral"
                : growth.data.monthly_growth_percent > 0
                  ? "success"
                  : "danger"
            }
          />
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DailySignupsChart data={growth.data?.daily_signups ?? []} loading={growth.loading} />
          <WeeklyActiveOrganizationsChart data={growth.data?.weekly_active_organizations ?? []} loading={growth.loading} />
        </div>
        <FeatureAdoptionChart data={growth.data?.feature_adoption ?? []} loading={growth.loading} />
      </section>
    </div>
  );
}

function HealthPill({ label, ok, loading }: { label: string; ok: boolean | null; loading: boolean }) {
  const { t } = useTranslation();
  if (loading || ok === null) {
    return (
      <span className="inline-flex h-6 w-32 animate-pulse items-center rounded-full bg-slate-100" aria-hidden />
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${
        ok ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200"
      }`}
    >
      {label}: {ok ? t("admin.configured") : t("admin.notConfigured")}
    </span>
  );
}
