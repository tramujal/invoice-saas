"use client";

import { useCallback, useEffect, useState } from "react";

import { InsightCard } from "@/components/dashboard/InsightCard";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { isRateLimitedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { DashboardInsightsResponse } from "@/lib/types";

function formatUpdatedAgo(t: TranslateFn, generatedAt: string): string {
  const generated = new Date(generatedAt).getTime();
  const minutes = Math.max(0, Math.floor((Date.now() - generated) / 60000));
  if (minutes < 1) return t("dashboard.insights.updatedJustNow");
  if (minutes === 1) return t("dashboard.insights.updatedOneMinuteAgo");
  return t("dashboard.insights.updatedMinutesAgo", { minutes });
}

export function BusinessInsightsSection() {
  const { t } = useTranslation();
  const toast = useToast();
  const [data, setData] = useState<DashboardInsightsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (opts?: { refresh?: boolean }) => {
      if (opts?.refresh) setRefreshing(true);
      else setLoading(true);
      if (!opts?.refresh) setError(false);

      try {
        const query = opts?.refresh ? "?refresh=true" : "";
        const json = await apiFetch<DashboardInsightsResponse>(
          orgPath(`dashboard/insights${query}`)
        );
        setData(json);
      } catch (err) {
        if (opts?.refresh) {
          // A failed manual refresh never blows away the insights already
          // on screen -- just a toast, matching how the assistant page
          // surfaces its own rate-limit errors.
          if (isRateLimitedError(err)) {
            toast.error(t("dashboard.insights.refreshRateLimited"));
          } else {
            toast.error(t("dashboard.insights.refreshError"));
          }
        } else {
          setError(true);
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [t, toast]
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const insights = data?.insights ?? [];
  const primary = insights.filter((i) => i.tier === "primary");
  const secondary = insights.filter((i) => i.tier === "secondary");

  return (
    <section aria-label="businessInsights">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">
            {t("dashboard.insights.heading")}
          </h2>
          {data ? (
            <p className="text-xs text-slate-400">{formatUpdatedAgo(t, data.generated_at)}</p>
          ) : null}
        </div>
        {data?.ai_available ? (
          <button
            type="button"
            onClick={() => void load({ refresh: true })}
            disabled={refreshing || loading}
            className="self-start rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 sm:self-auto"
          >
            {refreshing ? t("dashboard.insights.refreshing") : t("dashboard.insights.refresh")}
          </button>
        ) : null}
      </div>

      <div className="mt-4">
        {loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" aria-hidden>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="animate-pulse rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
              >
                <div className="h-4 w-2/3 rounded bg-slate-200" />
                <div className="mt-3 h-3 w-full rounded bg-slate-100" />
                <div className="mt-1.5 h-3 w-4/5 rounded bg-slate-100" />
              </div>
            ))}
          </div>
        ) : error ? (
          <div
            className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            role="alert"
          >
            {t("dashboard.insights.loadError")}
          </div>
        ) : insights.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/80 px-4 py-6 text-center text-sm text-slate-500">
            {t("dashboard.insights.empty")}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {primary.map((insight) => (
                <InsightCard key={insight.id} insight={insight} />
              ))}
            </div>
            {secondary.length > 0 ? (
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                {secondary.map((insight) => (
                  <InsightCard key={insight.id} insight={insight} compact />
                ))}
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
