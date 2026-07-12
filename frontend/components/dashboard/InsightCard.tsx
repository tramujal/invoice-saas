"use client";

import Link from "next/link";

import { insightCtaHref } from "@/lib/insights-cta";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import { formatCurrency } from "@/lib/money";
import type { Insight, InsightCta, InsightSeverity } from "@/lib/types";

const SEVERITY_CARD_CLASS: Record<InsightSeverity, string> = {
  critical: "border-red-200 bg-red-50",
  warning: "border-amber-200 bg-amber-50",
  positive: "border-emerald-200 bg-emerald-50",
  info: "border-slate-200 bg-white",
};

const SEVERITY_BADGE_CLASS: Record<InsightSeverity, string> = {
  critical: "bg-red-100 text-red-900 ring-red-200/80",
  warning: "bg-amber-100 text-amber-900 ring-amber-200/80",
  positive: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  info: "bg-slate-100 text-slate-700 ring-slate-200/80",
};

function ctaLabel(t: TranslateFn, cta: InsightCta): string {
  switch (cta.type) {
    case "view_overdue_invoices":
      return t("dashboard.insights.cta.viewOverdueInvoices");
    case "view_due_soon_invoices":
      return t("dashboard.insights.cta.viewDueSoonInvoices");
    case "review_pending_invoices":
      return t("dashboard.insights.cta.reviewPendingInvoices");
    case "create_invoice":
      return t("dashboard.insights.cta.createInvoice");
    case "view_products":
      return t("dashboard.insights.cta.viewProducts");
    case "ask_assistant":
      return t("dashboard.insights.cta.askAssistant");
    default:
      return t("dashboard.insights.cta.askAssistant");
  }
}

type InsightCardProps = {
  insight: Insight;
  compact?: boolean;
};

export function InsightCard({ insight, compact = false }: InsightCardProps) {
  const { t } = useTranslation();
  const cardClass = SEVERITY_CARD_CLASS[insight.severity] ?? SEVERITY_CARD_CLASS.info;
  const badgeClass = SEVERITY_BADGE_CLASS[insight.severity] ?? SEVERITY_BADGE_CLASS.info;

  return (
    <article className={`rounded-2xl border ${cardClass} p-4 shadow-sm sm:p-5`}>
      <div className="flex items-start justify-between gap-2">
        <h3
          className={`font-semibold text-slate-900 ${compact ? "text-sm" : "text-base"}`}
        >
          {insight.title}
        </h3>
        <span
          className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${badgeClass}`}
        >
          {t(`dashboard.insights.severity.${insight.severity}`)}
        </span>
      </div>

      <p className={`mt-1.5 text-slate-700 ${compact ? "text-xs" : "text-sm"}`}>
        {insight.message}
      </p>

      {insight.suggestion ? (
        <p className="mt-2 text-xs text-slate-500">{insight.suggestion}</p>
      ) : null}

      {insight.metric && insight.metric.currency_code && insight.metric.value !== null ? (
        <p className="mt-2 text-sm font-semibold text-slate-900">
          {formatCurrency(insight.metric.value, insight.metric.currency_code)}
          {insight.metric.percentage !== null ? (
            <span className="ml-1.5 text-xs font-medium text-slate-500">
              ({insight.metric.percentage >= 0 ? "+" : ""}
              {insight.metric.percentage.toFixed(1)}%)
            </span>
          ) : null}
        </p>
      ) : null}

      {insight.cta ? (
        <Link
          href={insightCtaHref(insight.cta)}
          className="mt-3 inline-flex items-center text-xs font-semibold text-slate-700 underline hover:text-slate-900"
        >
          {ctaLabel(t, insight.cta)} →
        </Link>
      ) : null}
    </article>
  );
}
