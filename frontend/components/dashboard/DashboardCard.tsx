"use client";

import type { ReactNode } from "react";

import { useTranslation } from "@/lib/i18n/useTranslation";

export type DashboardCardTone = "neutral" | "success" | "info";

const TONE_CARD_CLASS: Record<DashboardCardTone, string> = {
  neutral: "border-slate-200 bg-white",
  success: "border-emerald-200 bg-emerald-50",
  info: "border-sky-200 bg-sky-50",
};

const TONE_ICON_CLASS: Record<DashboardCardTone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  success: "bg-emerald-100 text-emerald-700",
  info: "bg-sky-100 text-sky-700",
};

type DashboardCardProps = {
  title: string;
  value: string;
  description?: string;
  loading?: boolean;
  tone?: DashboardCardTone;
  icon?: ReactNode;
};

export function DashboardCard({
  title,
  value,
  description,
  loading = false,
  tone = "neutral",
  icon,
}: DashboardCardProps) {
  const { t } = useTranslation();

  return (
    <article className={`rounded-2xl border p-5 shadow-sm sm:p-6 ${TONE_CARD_CLASS[tone]}`}>
      <div className="flex items-center gap-3">
        {icon ? (
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${TONE_ICON_CLASS[tone]}`}
          >
            {icon}
          </span>
        ) : null}
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {title}
        </h2>
      </div>
      {loading ? (
        <div className="mt-3 space-y-2" aria-hidden>
          <div className="h-8 w-24 animate-pulse rounded-lg bg-slate-200" />
          {description ? (
            <div className="h-4 w-32 animate-pulse rounded bg-slate-100" />
          ) : null}
        </div>
      ) : (
        <>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
            {value}
          </p>
          {description ? (
            <p className="mt-1 text-sm text-slate-500">{description}</p>
          ) : null}
        </>
      )}
      {loading ? (
        <span className="sr-only">
          {t("common.loadingLabel", { label: title.toLowerCase() })}
        </span>
      ) : null}
    </article>
  );
}
