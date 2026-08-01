"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { useTranslation } from "@/lib/i18n/useTranslation";

export type DashboardCardTone = "neutral" | "success" | "info" | "danger";

const TONE_CARD_CLASS: Record<DashboardCardTone, string> = {
  neutral: "border-slate-200 bg-white",
  success: "border-emerald-200 bg-emerald-50",
  info: "border-sky-200 bg-sky-50",
  danger: "border-red-200 bg-red-50",
};

const TONE_ICON_CLASS: Record<DashboardCardTone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  success: "bg-emerald-100 text-emerald-700",
  info: "bg-sky-100 text-sky-700",
  danger: "bg-red-100 text-red-700",
};

type DashboardCardProps = {
  title: string;
  value: string;
  description?: string;
  loading?: boolean;
  tone?: DashboardCardTone;
  icon?: ReactNode;
  /** Phase UX4 -- when set, the whole card becomes a link to that
   * module's own page (e.g. the Organizations count card links to
   * /admin/organizations), with a hover elevation cue signaling it's
   * interactive. Omit for cards with no corresponding page to navigate
   * to -- a card that *looks* clickable but goes nowhere is worse than
   * one that plainly isn't. */
  href?: string;
};

const INTERACTIVE_CLASS =
  "transition duration-150 hover:-translate-y-0.5 hover:shadow-md focus-visible:-translate-y-0.5 focus-visible:shadow-md outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2";

export function DashboardCard({
  title,
  value,
  description,
  loading = false,
  tone = "neutral",
  icon,
  href,
}: DashboardCardProps) {
  const { t } = useTranslation();

  const cardClass = `block rounded-2xl border p-5 shadow-sm sm:p-6 ${TONE_CARD_CLASS[tone]} ${href ? INTERACTIVE_CLASS : ""}`;

  const content = (
    <>
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
        {href ? (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
            className="ml-auto shrink-0 text-slate-300"
          >
            <path d="m9 18 6-6-6-6" />
          </svg>
        ) : null}
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
    </>
  );

  if (href) {
    return (
      <Link href={href} className={cardClass} aria-label={`${title}: ${value}`}>
        {content}
      </Link>
    );
  }

  return <article className={cardClass}>{content}</article>;
}
