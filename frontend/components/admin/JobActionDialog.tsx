"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";

export type JobActionMode = "retry" | "cancel";

type JobActionDialogProps = {
  open: boolean;
  mode: JobActionMode;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (reason: string) => void;
};

/** Confirmation dialog for the two Platform Admin job actions (operational
 * retry, cancel) -- lighter than SuspendReactivateDialog/UserActionDialog
 * (no typed confirmation, since a job id isn't a human-memorable string the
 * way an org name or email is) but still requires a written reason, matching
 * PlatformJobActionRequest's backend validation (min_length=1). Portal,
 * Escape-to-close, backdrop click, never optimistic -- same conventions as
 * every other admin confirmation dialog. */
export function JobActionDialog({ open, mode, submitting, error, onClose, onConfirm }: JobActionDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [reason, setReason] = useState("");
  const reasonInputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setReason("");
    reasonInputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open || !mounted) return null;

  const reasonValid = reason.trim().length > 0;
  const canSubmit = reasonValid && !submitting;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onConfirm(reason.trim());
  }

  const title = mode === "retry" ? t("jobs.retryDialogTitle") : t("jobs.cancelDialogTitle");
  const description = mode === "retry" ? t("jobs.retryDialogDescription") : t("jobs.cancelDialogDescription");
  const confirmLabel = mode === "retry" ? t("jobs.retryConfirmButton") : t("jobs.cancelConfirmButton");

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-backdrop-in items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-md animate-modal-in rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        <p className="mt-1 text-xs text-slate-500">{description}</p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label htmlFor="job-action-reason" className="text-xs font-medium text-slate-600">
              {t("admin.reasonLabel")}
            </label>
            <Textarea
              id="job-action-reason"
              ref={reasonInputRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="mt-1 resize-none"
              disabled={submitting}
              placeholder={t("admin.reasonPlaceholder")}
            />
          </div>

          {error ? (
            <p className="text-xs text-red-700" role="alert">
              {error}
            </p>
          ) : null}

          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant={mode === "cancel" ? "danger" : "primary"} disabled={!canSubmit}>
              {submitting ? t("common.saving") : confirmLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
