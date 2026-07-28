"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { getJobStatusLabel, getJobTypeLabel, JOB_STATUS_BADGE_CLASS } from "@/lib/job-status";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformBackgroundJobDetail } from "@/lib/types";

type JobDetailDrawerProps = {
  job: PlatformBackgroundJobDetail | null;
  onClose: () => void;
  formatTimestamp: (value: string | null) => string;
};

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Read-only detail view for a single BackgroundJob row -- the payload
 * shown here is never a secret (see BackgroundJob.payload's own docstring
 * in app/models.py: every job type's payload only ever contains IDs/
 * validated data), so this renders it as plain text the same way
 * AuditLogEntryDrawer renders audit details. */
export function JobDetailDrawer({ job, onClose, formatTimestamp }: JobDetailDrawerProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!job) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [job, onClose]);

  if (!job || !mounted) return null;

  const payloadEntries = Object.entries(job.payload);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("jobs.detailsTitle")}
        className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-sm font-semibold text-slate-900">{t("jobs.detailsTitle")}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        <dl className="mt-4 max-h-[60vh] space-y-3 overflow-y-auto text-sm">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{t("jobs.fieldId")}</dt>
            <dd className="break-all text-slate-900">{job.id}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{t("jobs.colJobType")}</dt>
            <dd className="text-slate-900" title={job.job_type}>
              {getJobTypeLabel(t, job.job_type)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{t("jobs.colStatus")}</dt>
            <dd>
              <Badge className={JOB_STATUS_BADGE_CLASS[job.status]}>{getJobStatusLabel(t, job.status)}</Badge>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("jobs.colOrganization")}
            </dt>
            <dd className="break-all text-slate-900">{job.organization_id ?? "—"}</dd>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{t("jobs.fieldQueue")}</dt>
              <dd className="text-slate-900">{job.queue}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("jobs.fieldPriority")}
              </dt>
              <dd className="text-slate-900">{job.priority}</dd>
            </div>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{t("jobs.fieldAttempts")}</dt>
            <dd className="text-slate-900">
              {job.attempts} / {job.max_attempts}
            </dd>
          </div>

          <div className="border-t border-slate-100 pt-3">
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("jobs.detailsSectionTiming")}
            </dt>
            <dd>
              <ul className="mt-1 space-y-1 rounded-lg bg-surface-muted p-3 text-xs">
                <li className="flex justify-between gap-4">
                  <span className="font-medium text-slate-600">{t("jobs.fieldAvailableAt")}</span>
                  <span className="text-right text-slate-900">{formatTimestamp(job.available_at)}</span>
                </li>
                <li className="flex justify-between gap-4">
                  <span className="font-medium text-slate-600">{t("jobs.fieldClaimedAt")}</span>
                  <span className="text-right text-slate-900">{formatTimestamp(job.claimed_at)}</span>
                </li>
                <li className="flex justify-between gap-4">
                  <span className="font-medium text-slate-600">{t("jobs.fieldClaimedBy")}</span>
                  <span className="break-all text-right text-slate-900">{job.claimed_by ?? "—"}</span>
                </li>
                <li className="flex justify-between gap-4">
                  <span className="font-medium text-slate-600">{t("jobs.fieldLeaseExpiresAt")}</span>
                  <span className="text-right text-slate-900">{formatTimestamp(job.lease_expires_at)}</span>
                </li>
                <li className="flex justify-between gap-4">
                  <span className="font-medium text-slate-600">{t("jobs.fieldStartedAt")}</span>
                  <span className="text-right text-slate-900">{formatTimestamp(job.started_at)}</span>
                </li>
                <li className="flex justify-between gap-4">
                  <span className="font-medium text-slate-600">{t("jobs.fieldCompletedAt")}</span>
                  <span className="text-right text-slate-900">{formatTimestamp(job.completed_at)}</span>
                </li>
                <li className="flex justify-between gap-4">
                  <span className="font-medium text-slate-600">{t("jobs.fieldFailedAt")}</span>
                  <span className="text-right text-slate-900">{formatTimestamp(job.failed_at)}</span>
                </li>
              </ul>
            </dd>
          </div>

          {job.last_error_code || job.last_error_message ? (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("jobs.fieldLastError")}
              </dt>
              <dd className="whitespace-pre-wrap text-red-700">
                {job.last_error_code ? `${job.last_error_code}: ` : ""}
                {job.last_error_message ?? "—"}
              </dd>
            </div>
          ) : null}

          {job.result_summary ? (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                {t("jobs.fieldResultSummary")}
              </dt>
              <dd className="whitespace-pre-wrap text-slate-900">{job.result_summary}</dd>
            </div>
          ) : null}

          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("jobs.fieldIdempotencyKey")}
            </dt>
            <dd className="break-all text-slate-900">{job.idempotency_key ?? "—"}</dd>
          </div>

          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("jobs.detailsSectionPayload")}
            </dt>
            {payloadEntries.length === 0 ? (
              <dd className="text-slate-500">{t("jobs.noPayload")}</dd>
            ) : (
              <dd>
                <ul className="mt-1 space-y-1 rounded-lg bg-surface-muted p-3">
                  {payloadEntries.map(([key, value]) => (
                    <li key={key} className="flex justify-between gap-4 text-xs">
                      <span className="font-medium text-slate-600">{key}</span>
                      <span className="break-all text-right text-slate-900">{renderValue(value)}</span>
                    </li>
                  ))}
                </ul>
              </dd>
            )}
          </div>
        </dl>

        <div className="mt-5 flex justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
