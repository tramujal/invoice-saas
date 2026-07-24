"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatUsage, getLimitStatus } from "@/lib/plan-limits";
import type { OrganizationEntitlements, OrganizationUsage } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

/** Read-only. Deliberately has no upgrade button and no payment UI --
 * Phase 14A defined entitlements, Phase 14B adds how much of each is
 * currently used (see app.services.organization_usage), but limit
 * enforcement itself is still a later phase: nothing here warns or
 * blocks, it only measures. */
export default function PlanAndLimitsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<OrganizationEntitlements | null>(null);
  const [usage, setUsage] = useState<OrganizationUsage | null>(null);
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
      const [entitlements, usageSnapshot] = await Promise.all([
        apiFetch<OrganizationEntitlements>(orgPath("entitlements"), { signal: controller.signal }),
        apiFetch<OrganizationUsage>(orgPath("usage"), { signal: controller.signal }),
      ]);
      setData(entitlements);
      setUsage(usageSnapshot);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setUsage(null);
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
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title={t("planAndLimits.title")} subtitle={t("planAndLimits.subtitle")} />
      <SettingsSubNav />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

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
            </>
          )}
        </div>
      </section>
    </div>
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
