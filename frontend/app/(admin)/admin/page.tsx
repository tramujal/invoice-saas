"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformDashboard } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

export default function PlatformAdminDashboardPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PlatformDashboard | null>(null);
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
      const json = await apiFetch<PlatformDashboard>("/admin/dashboard", {
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

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title={t("admin.dashboardTitle")}
        subtitle={t("admin.dashboardSubtitle")}
        actions={
          <Button type="button" variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? t("common.refreshing") : t("common.refresh")}
          </Button>
        }
      />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      <section
        className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
        aria-label={t("admin.systemHealthTitle")}
      >
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("admin.systemHealthTitle")}
        </h2>
        <div className="mt-3 flex flex-wrap gap-2">
          <HealthPill
            label={t("admin.databaseLabel")}
            ok={data?.health.database_reachable ?? null}
            loading={loading}
          />
          <HealthPill
            label={t("admin.emailProviderLabel")}
            ok={data ? data.health.email_provider_configured : null}
            loading={loading}
          />
          <HealthPill
            label={t("admin.aiProviderLabel")}
            ok={data ? data.health.ai_provider_configured : null}
            loading={loading}
          />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <DashboardCard
          title={t("admin.organizationsTotal")}
          value={data ? String(data.organizations_total) : "—"}
          description={
            data ? t("admin.new7d30d", { d7: data.organizations_new_7d, d30: data.organizations_new_30d }) : undefined
          }
          loading={loading}
        />
        <DashboardCard
          title={t("admin.usersTotal")}
          value={data ? String(data.users_total) : "—"}
          description={data ? t("admin.new7d30d", { d7: data.users_new_7d, d30: data.users_new_30d }) : undefined}
          loading={loading}
        />
        <DashboardCard
          title={t("admin.invoicesTotal")}
          value={data ? String(data.invoices_total) : "—"}
          loading={loading}
        />
        <DashboardCard
          title={t("admin.quotesTotal")}
          value={data ? String(data.quotes_total) : "—"}
          loading={loading}
        />
        <DashboardCard
          title={t("admin.customersTotal")}
          value={data ? String(data.customers_total) : "—"}
          loading={loading}
        />
        <DashboardCard
          title={t("admin.productsTotal")}
          value={data ? String(data.products_total) : "—"}
          loading={loading}
        />
        <DashboardCard
          title={t("admin.reminderEmails7d")}
          value={data ? String(data.reminder_emails_sent_7d) : "—"}
          description={data ? t("admin.reminderEmailsFailed7d", { count: data.reminder_emails_failed_7d }) : undefined}
          loading={loading}
        />
        <DashboardCard
          title={t("admin.aiActionsExecuted7d")}
          value={data ? String(data.ai_actions_executed_7d) : "—"}
          loading={loading}
        />
      </div>
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
