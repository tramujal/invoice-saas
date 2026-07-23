"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatPlanLimit } from "@/lib/plan-limits";
import type { OrganizationEntitlements } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

/** Read-only. Deliberately has no upgrade button, no payment UI, and no
 * fake usage numbers -- Phase 14A defines entitlements only; usage
 * tracking and any commercial upgrade flow are later phases (see
 * app.services.entitlements's own module docstring on the backend). */
export default function PlanAndLimitsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<OrganizationEntitlements | null>(null);
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
      const json = await apiFetch<OrganizationEntitlements>(orgPath("entitlements"), {
        signal: controller.signal,
      });
      setData(json);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setData(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  const limitRows: { labelKey: string; value: number | null | undefined }[] = [
    { labelKey: "planAndLimits.rowUsers", value: data?.limits.max_users },
    { labelKey: "planAndLimits.rowCustomers", value: data?.limits.max_customers },
    { labelKey: "planAndLimits.rowProducts", value: data?.limits.max_products },
    { labelKey: "planAndLimits.rowInvoices", value: data?.limits.max_invoices_per_month },
    { labelKey: "planAndLimits.rowQuotes", value: data?.limits.max_quotes_per_month },
    { labelKey: "planAndLimits.rowAiActions", value: data?.limits.max_ai_actions_per_month },
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
          {limitRows.map(({ labelKey, value }) => (
            <div key={labelKey} className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-sm font-medium text-slate-700">{t(labelKey)}</dt>
              <dd className="text-sm text-slate-900">
                {loading ? (
                  <span className="inline-flex h-4 w-16 animate-pulse rounded bg-slate-100" aria-hidden />
                ) : (
                  formatPlanLimit(value ?? null, t)
                )}
              </dd>
            </div>
          ))}
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
                t("planAndLimits.storageMbValue", { mb: data?.limits.storage_limit_mb ?? 0 })
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
