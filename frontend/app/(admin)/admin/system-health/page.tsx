"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, apiFetch } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformSystemHealth } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

export default function PlatformSystemHealthPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PlatformSystemHealth | null>(null);
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
      const json = await apiFetch<PlatformSystemHealth>("/admin/system/health", {
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
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        title={t("admin.systemHealthTitle")}
        subtitle={t("admin.systemHealthSubtitle")}
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

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <dl className="divide-y divide-slate-100">
          <Row label={t("admin.databaseLabel")} loading={loading}>
            {data ? (
              <StatusBadge ok={data.database_reachable} okLabel={t("admin.databaseReachable")} badLabel={t("admin.databaseUnreachable")} />
            ) : null}
          </Row>
          <Row label={t("admin.emailProviderLabel")} loading={loading}>
            {data ? (
              <StatusBadge
                ok={data.email_provider_configured}
                okLabel={data.email_provider ? t("admin.configuredAs", { provider: data.email_provider }) : t("admin.configured")}
                badLabel={t("admin.notConfigured")}
              />
            ) : null}
          </Row>
          <Row label={t("admin.aiProviderLabel")} loading={loading}>
            {data ? (
              <StatusBadge
                ok={data.ai_provider_configured}
                okLabel={data.ai_provider ? t("admin.configuredAs", { provider: data.ai_provider }) : t("admin.configured")}
                badLabel={t("admin.notConfigured")}
              />
            ) : null}
          </Row>
        </dl>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">{t("admin.reminderPipelineTitle")}</h2>
        <p className="mt-1 text-sm text-slate-500">{t("admin.reminderPipelineSubtitle")}</p>
        <div className="mt-4 grid grid-cols-3 gap-4 text-center">
          <Stat label={t("admin.reminderPending")} value={data?.reminder_emails_pending} loading={loading} />
          <Stat label={t("admin.reminderSent7d")} value={data?.reminder_emails_sent_7d} loading={loading} />
          <Stat label={t("admin.reminderFailed7d")} value={data?.reminder_emails_failed_7d} loading={loading} />
        </div>
      </section>
    </div>
  );
}

function Row({ label, loading, children }: { label: string; loading: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4">
      <dt className="text-sm font-medium text-slate-700">{label}</dt>
      <dd>
        {loading ? (
          <span className="inline-flex h-6 w-28 animate-pulse rounded-full bg-slate-100" aria-hidden />
        ) : (
          children
        )}
      </dd>
    </div>
  );
}

function StatusBadge({ ok, okLabel, badLabel }: { ok: boolean; okLabel: string; badLabel: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${
        ok ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200"
      }`}
    >
      {ok ? okLabel : badLabel}
    </span>
  );
}

function Stat({ label, value, loading }: { label: string; value: number | undefined; loading: boolean }) {
  return (
    <div>
      {loading ? (
        <div className="mx-auto h-7 w-10 animate-pulse rounded bg-slate-100" aria-hidden />
      ) : (
        <p className="text-xl font-semibold text-slate-900">{value ?? "—"}</p>
      )}
      <p className="mt-1 text-xs text-slate-500">{label}</p>
    </div>
  );
}
