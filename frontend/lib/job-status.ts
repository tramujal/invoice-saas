import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { BackgroundJobStatus } from "@/lib/types";

export const BACKGROUND_JOB_STATUSES: readonly BackgroundJobStatus[] = [
  "pending",
  "claimed",
  "running",
  "retry_scheduled",
  "succeeded",
  "permanently_failed",
  "cancelled",
] as const;

/** Same hook-free translation-lookup convention as lib/quote-status.ts. */
export function getJobStatusLabel(t: TranslateFn, status: BackgroundJobStatus): string {
  return t(`jobs.status.${status}`);
}

export const JOB_STATUS_BADGE_CLASS: Record<BackgroundJobStatus, string> = {
  pending: "bg-slate-100 text-slate-700 ring-slate-200/80",
  claimed: "bg-sky-100 text-sky-900 ring-sky-200/80",
  running: "bg-sky-100 text-sky-900 ring-sky-200/80",
  retry_scheduled: "bg-amber-100 text-amber-900 ring-amber-200/80",
  succeeded: "bg-emerald-100 text-emerald-900 ring-emerald-200/80",
  permanently_failed: "bg-red-100 text-red-900 ring-red-200/80",
  cancelled: "bg-slate-100 text-slate-700 ring-slate-200/80",
};

export const JOB_TYPES = ["webhook.deliver", "webhook.retry"] as const;

export function getJobTypeLabel(t: TranslateFn, jobType: string): string {
  const key: Record<string, string> = {
    "webhook.deliver": "jobs.jobTypeWebhookDeliver",
    "webhook.retry": "jobs.jobTypeWebhookRetry",
  };
  const translationKey = key[jobType];
  return translationKey ? t(translationKey) : jobType;
}
