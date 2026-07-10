"use client";

import { useTranslation } from "@/lib/i18n/useTranslation";

type DashboardCardProps = {
  title: string;
  value: string;
  description?: string;
  loading?: boolean;
};

export function DashboardCard({
  title,
  value,
  description,
  loading = false,
}: DashboardCardProps) {
  const { t } = useTranslation();

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
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
