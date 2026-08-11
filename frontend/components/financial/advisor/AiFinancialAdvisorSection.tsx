"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { getCapabilityDeniedDetail, getPlanLimitReachedDetail } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { GenerateInsightRequest, InsightReportResponse } from "@/lib/types";

import { HealthBadge } from "./AdvisorBadges";
import { ObservationCard } from "./ObservationCard";
import { RecommendationCard } from "./RecommendationCard";

const POLL_INTERVAL_MS = 3000;

const ERROR_CODE_KEY: Record<string, string> = {
  ai_unavailable: "financial.advisor.error.aiUnavailable",
  provider_timeout: "financial.advisor.error.providerTimeout",
  provider_error: "financial.advisor.error.providerError",
  invalid_response: "financial.advisor.error.invalidResponse",
};

type Props = {
  planRestricted: boolean;
};

/** Section: AI Financial Advisor -- a professional, minimal EXECUTIVE
 * REPORT (never a chat interface), built entirely from
 * app.financial_intelligence.recommendations' strictly-validated
 * output. Never blocks the rest of the dashboard: fetches its own latest
 * report independently on mount and polls only while a generation is
 * actually pending (a real background job, not a synchronous request the
 * user waits on). */
export function AiFinancialAdvisorSection({ planRestricted }: Props) {
  const { t } = useTranslation();
  const [report, setReport] = useState<InsightReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    };
  }, []);

  const fetchLatest = useCallback(async () => {
    try {
      const data = await apiFetch<InsightReportResponse | null>(
        orgPath("financial-intelligence/insights/latest")
      );
      if (!mountedRef.current) return;
      setReport(data);
      if (data && data.status === "pending") {
        pollTimeoutRef.current = setTimeout(() => void fetchLatest(), POLL_INTERVAL_MS);
      }
    } catch {
      // A denied/plan-restricted GET is already covered by the
      // `planRestricted` prop's own dedicated state below; any other
      // failure here just leaves the section in its empty state rather
      // than blocking the rest of the dashboard.
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (planRestricted) {
      setLoading(false);
      return;
    }
    void fetchLatest();
  }, [planRestricted, fetchLatest]);

  const handleGenerate = useCallback(
    async (force: boolean) => {
      setActionPending(true);
      setActionError(null);
      try {
        const body: GenerateInsightRequest = { force };
        const data = await apiFetch<InsightReportResponse>(
          orgPath("financial-intelligence/insights/generate"),
          { method: "POST", body: JSON.stringify(body) }
        );
        if (!mountedRef.current) return;
        setReport(data);
        if (data.status === "pending") {
          pollTimeoutRef.current = setTimeout(() => void fetchLatest(), POLL_INTERVAL_MS);
        }
      } catch (e) {
        if (!mountedRef.current) return;
        const capabilityDenied = getCapabilityDeniedDetail(e);
        const quotaExceeded = getPlanLimitReachedDetail(e);
        if (capabilityDenied) {
          setActionError(t("financial.advisor.planRestrictedDescription"));
        } else if (quotaExceeded) {
          setActionError(
            t("financial.advisor.quotaExceeded", {
              used: String(quotaExceeded.used),
              limit: String(quotaExceeded.limit),
            })
          );
        } else {
          setActionError(e instanceof ApiError ? e.message : t("financial.advisor.genericError"));
        }
      } finally {
        if (mountedRef.current) setActionPending(false);
      }
    },
    // `t` is genuinely a dependency: its identity changes when the
    // organization's language does, and omitting it would let this
    // callback keep formatting error messages with a stale translator
    // after a language switch.
    [fetchLatest, t]
  );

  const renderButton = (label: string, force: boolean, variant: "primary" | "secondary" = "primary") => (
    <button
      type="button"
      onClick={() => void handleGenerate(force)}
      disabled={actionPending}
      className={
        variant === "primary"
          ? "rounded-lg bg-slate-900 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          : "rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
      }
    >
      {actionPending ? t("financial.advisor.generating") : label}
    </button>
  );

  return (
    <section aria-label={t("financial.advisor.heading")} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">{t("financial.advisor.heading")}</h2>
          <p className="mt-1 text-sm text-slate-500">{t("financial.advisor.subtitle")}</p>
        </div>
      </div>

      {actionError && !planRestricted ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {actionError}
        </div>
      ) : null}

      {planRestricted ? (
        <EmptyState
          title={t("financial.advisor.planRestrictedTitle")}
          description={t("financial.advisor.planRestrictedDescription")}
        />
      ) : loading ? (
        <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      ) : !report ? (
        <EmptyState
          title={t("financial.advisor.emptyTitle")}
          description={t("financial.advisor.emptyDescription")}
          action={renderButton(t("financial.advisor.generateButton"), false)}
        />
      ) : report.status === "pending" ? (
        <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" aria-hidden />
          <div>
            <p className="text-sm font-medium text-slate-800">{t("financial.advisor.pendingTitle")}</p>
            <p className="text-xs text-slate-500">{t("financial.advisor.pendingDescription")}</p>
          </div>
        </div>
      ) : report.status === "failed" ? (
        <EmptyState
          title={t("financial.advisor.failedTitle")}
          description={t(
            (report.error_code && ERROR_CODE_KEY[report.error_code]) || "financial.advisor.error.generic"
          )}
          action={renderButton(t("financial.advisor.tryAgainButton"), true, "secondary")}
        />
      ) : report.analysis ? (
        <div className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-4">
            <div className="flex items-center gap-2">
              <HealthBadge health={report.analysis.overall_health} />
              {report.reused ? (
                <span className="text-xs text-slate-400">{t("financial.advisor.cachedIndicator")}</span>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-400">
                {report.generated_at
                  ? t("financial.advisor.lastGenerated", {
                      date: new Date(report.generated_at).toLocaleString(),
                    })
                  : ""}
              </span>
              {renderButton(t("financial.advisor.refreshButton"), true, "secondary")}
            </div>
          </div>

          <p className="text-sm text-slate-700">{report.analysis.executive_summary}</p>
          <p className="rounded-xl bg-slate-50 px-4 py-3 text-xs text-slate-500">{report.analysis.confidence_notice}</p>

          {report.analysis.observations.length > 0 ? (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-800">{t("financial.advisor.observationsHeading")}</h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {report.analysis.observations.map((observation, i) => (
                  <ObservationCard key={i} observation={observation} />
                ))}
              </div>
            </div>
          ) : null}

          {report.analysis.recommendations.length > 0 ? (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-800">{t("financial.advisor.recommendationsHeading")}</h3>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {report.analysis.recommendations.map((recommendation, i) => (
                  <RecommendationCard key={i} recommendation={recommendation} />
                ))}
              </div>
            </div>
          ) : null}

          <div>
            <h3 className="text-sm font-semibold text-slate-800">{t("financial.advisor.forecastCommentaryHeading")}</h3>
            <p className="mt-1 text-sm text-slate-600">{report.analysis.forecast_commentary}</p>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {(
              [
                ["strengths", "financial.advisor.strengthsHeading", report.analysis.strengths],
                ["risks", "financial.advisor.risksHeading", report.analysis.risks],
                ["opportunities", "financial.advisor.opportunitiesHeading", report.analysis.opportunities],
                ["next_actions", "financial.advisor.nextActionsHeading", report.analysis.next_actions],
              ] as const
            ).map(([key, headingKey, items]) =>
              items.length > 0 ? (
                <div key={key}>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t(headingKey)}</h4>
                  <ul className="mt-2 space-y-1.5">
                    {items.map((item, i) => (
                      <li key={i} className="text-xs text-slate-600">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null
            )}
          </div>

          <p className="border-t border-slate-100 pt-3 text-[11px] text-slate-400">{report.analysis.disclaimer}</p>
        </div>
      ) : null}
    </section>
  );
}
