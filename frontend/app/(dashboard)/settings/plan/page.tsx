"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ManageBillingButton } from "@/components/settings/ManageBillingButton";
import { PlanSelector } from "@/components/settings/PlanSelector";
import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { Badge } from "@/components/ui/Badge";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { useTranslation, type TranslateFn } from "@/lib/i18n/useTranslation";
import { formatUsage, getLimitStatus } from "@/lib/plan-limits";
import type { OrganizationEntitlements, OrganizationUsage, Subscription, SubscriptionStatus } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

const STATUS_BADGE_CLASS: Record<SubscriptionStatus, string> = {
  trialing: "bg-sky-50 text-sky-700 ring-sky-200",
  active: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  past_due: "bg-amber-50 text-amber-700 ring-amber-200",
  paused: "bg-slate-100 text-slate-600 ring-slate-200",
  canceled: "bg-red-50 text-red-700 ring-red-200",
  expired: "bg-red-50 text-red-700 ring-red-200",
  inactive: "bg-slate-100 text-slate-600 ring-slate-200",
};

const STATUS_LABEL_KEY: Record<SubscriptionStatus, string> = {
  trialing: "planAndLimits.statusTrialing",
  active: "planAndLimits.statusActive",
  past_due: "planAndLimits.statusPastDue",
  paused: "planAndLimits.statusPaused",
  canceled: "planAndLimits.statusCanceled",
  expired: "planAndLimits.statusExpired",
  inactive: "planAndLimits.statusInactive",
};

function formatDate(value: string, locale: string): string {
  return new Date(value).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

/** Whole days remaining until trial_end, floored at 0 -- never negative
 * even if trial_end has already passed but expire_trial() hasn't run yet
 * (there is no scheduled job for that in this phase). */
function trialDaysRemaining(trialEnd: string): number {
  const ms = new Date(trialEnd).getTime() - Date.now();
  return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
}

function billingPeriodLabel(subscription: Subscription, t: TranslateFn): string {
  return subscription.billing_period === "yearly"
    ? t("planAndLimits.billingPeriodYearly")
    : t("planAndLimits.billingPeriodMonthly");
}

/** Read-only. Deliberately has no upgrade button and no payment UI --
 * Phase 14A defined entitlements, Phase 14B adds how much of each is
 * currently used (see app.services.organization_usage), but limit
 * enforcement itself is still a later phase: nothing here warns or
 * blocks, it only measures. */
export default function PlanAndLimitsPage() {
  const { t, language } = useTranslation();
  const [data, setData] = useState<OrganizationEntitlements | null>(null);
  const [usage, setUsage] = useState<OrganizationUsage | null>(null);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
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
      const [entitlements, usageSnapshot, subscriptionResponse] = await Promise.all([
        apiFetch<OrganizationEntitlements>(orgPath("entitlements"), { signal: controller.signal }),
        apiFetch<OrganizationUsage>(orgPath("usage"), { signal: controller.signal }),
        apiFetch<Subscription>(orgPath("subscription"), { signal: controller.signal }),
      ]);
      setData(entitlements);
      setUsage(usageSnapshot);
      setSubscription(subscriptionResponse);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setUsage(null);
      setSubscription(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const usageRows: { labelKey: string; used: number | undefined; limit: number | null | undefined }[] = [
    { labelKey: "planAndLimits.rowUsers", used: usage?.users.used, limit: data?.limits.max_users },
    { labelKey: "planAndLimits.rowCustomers", used: usage?.customers.used, limit: data?.limits.max_customers },
    { labelKey: "planAndLimits.rowProducts", used: usage?.products.used, limit: data?.limits.max_products },
    { labelKey: "planAndLimits.rowInvoices", used: usage?.invoices.used, limit: data?.limits.max_invoices_per_month },
    { labelKey: "planAndLimits.rowQuotes", used: usage?.quotes.used, limit: data?.limits.max_quotes_per_month },
    {
      labelKey: "planAndLimits.rowAiActions",
      used: usage?.ai_actions.used,
      limit: data?.limits.max_ai_actions_per_month,
    },
  ];

  return (
    <PageContainer width="form">
      <PageHeader title={t("planAndLimits.title")} subtitle={t("planAndLimits.subtitle")} />
      <SettingsSubNav />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">
            {t("planAndLimits.sectionSubscription")}
          </h2>
          <ManageBillingButton />
        </div>
        <dl className="divide-y divide-slate-100">
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm font-medium text-slate-700">{t("planAndLimits.rowStatus")}</dt>
            <dd className="text-sm text-slate-900">
              {loading || !subscription ? (
                <span className="inline-flex h-5 w-20 animate-pulse rounded-full bg-slate-100" aria-hidden />
              ) : (
                <Badge className={STATUS_BADGE_CLASS[subscription.status]}>
                  {t(STATUS_LABEL_KEY[subscription.status])}
                </Badge>
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm font-medium text-slate-700">{t("planAndLimits.rowBillingPeriod")}</dt>
            <dd className="text-sm text-slate-900">
              {loading || !subscription ? (
                <span className="inline-flex h-4 w-16 animate-pulse rounded bg-slate-100" aria-hidden />
              ) : (
                billingPeriodLabel(subscription, t)
              )}
            </dd>
          </div>
          {!loading && subscription?.status === "trialing" && subscription.trial_end ? (
            <div className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-sm font-medium text-slate-700">{t("planAndLimits.rowTrialRemaining")}</dt>
              <dd className="text-sm text-slate-900">
                {t("planAndLimits.trialDaysRemaining", { days: trialDaysRemaining(subscription.trial_end) })}
              </dd>
            </div>
          ) : null}
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm font-medium text-slate-700">{t("planAndLimits.rowCurrentPeriodEnd")}</dt>
            <dd className="text-sm text-slate-900">
              {loading || !subscription ? (
                <span className="inline-flex h-4 w-24 animate-pulse rounded bg-slate-100" aria-hidden />
              ) : (
                formatDate(subscription.current_period_end, language)
              )}
            </dd>
          </div>
          {!loading && subscription?.cancel_at_period_end ? (
            <div className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-sm font-medium text-slate-700">{t("planAndLimits.rowCancelAtPeriodEnd")}</dt>
              <dd className="text-sm text-slate-900">
                <Badge className="bg-amber-50 text-amber-700 ring-amber-200">
                  {t("planAndLimits.cancelAtPeriodEndBadge")}
                </Badge>
              </dd>
            </div>
          ) : null}
        </dl>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("planAndLimits.currentPlanLabel")}
            </p>
            {loading ? (
              <span className="mt-1 inline-flex h-6 w-24 animate-pulse rounded-full bg-slate-100" aria-hidden />
            ) : (
              <p className="mt-1 text-lg font-semibold text-slate-900">{data?.plan_name}</p>
            )}
          </div>
        </div>

        <dl className="divide-y divide-slate-100">
          {usageRows.map(({ labelKey, used, limit }) => {
            const status = loading ? null : getLimitStatus(used ?? 0, limit ?? null);
            return (
              <div key={labelKey} className="flex items-center justify-between gap-4 px-5 py-3">
                <dt className="text-sm font-medium text-slate-700">{t(labelKey)}</dt>
                <dd className="flex items-center gap-2 text-sm text-slate-900">
                  {loading ? (
                    <span className="inline-flex h-4 w-16 animate-pulse rounded bg-slate-100" aria-hidden />
                  ) : (
                    <>
                      {status ? (
                        <Badge
                          className={
                            status === "reached"
                              ? "bg-red-50 text-red-700 ring-red-200"
                              : "bg-amber-50 text-amber-700 ring-amber-200"
                          }
                        >
                          {status === "reached"
                            ? t("planAndLimits.badgeReached")
                            : t("planAndLimits.badgeNearLimit")}
                        </Badge>
                      ) : null}
                      {formatUsage(used ?? 0, limit ?? null, t)}
                    </>
                  )}
                </dd>
              </div>
            );
          })}
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm font-medium text-slate-700">{t("planAndLimits.rowStorage")}</dt>
            <dd className="text-sm text-slate-900">
              {loading ? (
                <span className="inline-flex h-4 w-16 animate-pulse rounded bg-slate-100" aria-hidden />
              ) : data?.limits.storage_limit_mb === null ? (
                t("planLimits.unlimited")
              ) : data?.limits.storage_limit_mb === 0 ? (
                t("planLimits.unavailable")
              ) : (
                t("planAndLimits.storageUsageValue", {
                  used: usage?.storage.used ?? 0,
                  mb: data?.limits.storage_limit_mb ?? 0,
                })
              )}
            </dd>
          </div>
        </dl>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
          {t("planAndLimits.sectionFeatures")}
        </h2>
        <div className="flex flex-wrap gap-2 px-5 py-4">
          {loading ? (
            <span className="inline-flex h-6 w-32 animate-pulse rounded-full bg-slate-100" aria-hidden />
          ) : (
            <>
              <FeatureBadge enabled={data?.features.custom_branding_enabled} labelKey="planAndLimits.featureCustomBranding" />
              <FeatureBadge enabled={data?.features.api_access_enabled} labelKey="planAndLimits.featureApiAccess" />
              <FeatureBadge enabled={data?.features.advanced_reports_enabled} labelKey="planAndLimits.featureAdvancedReports" />
              <FeatureBadge enabled={data?.features.analytics_enabled} labelKey="planAndLimits.featureAnalytics" />
              <FeatureBadge enabled={data?.features.forecasting_enabled} labelKey="planAndLimits.featureForecasting" />
              <FeatureBadge enabled={data?.features.ai_enabled} labelKey="planAndLimits.featureAi" />
              <FeatureBadge enabled={data?.features.background_jobs_enabled} labelKey="planAndLimits.featureBackgroundJobs" />
            </>
          )}
        </div>
      </section>

      <PlanSelector subscription={subscription} />
    </PageContainer>
  );
}

function FeatureBadge({ enabled, labelKey }: { enabled: boolean | undefined; labelKey: string }) {
  const { t } = useTranslation();
  return (
    <Badge
      className={
        enabled
          ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
          : "bg-slate-100 text-slate-500 ring-slate-200"
      }
    >
      {t(labelKey)}
    </Badge>
  );
}
