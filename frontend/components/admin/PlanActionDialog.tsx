"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";

export type PlanActionMode = "activate" | "deactivate" | "make-default";

type PlanActionDialogProps = {
  open: boolean;
  mode: PlanActionMode;
  planName: string;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (reason: string) => void;
};

/** Shared confirmation dialog for activate/deactivate/make-default --
 * all three are a single-field toggle on one plan (see
 * app.routers.platform_admin's _toggle_plan_active/make_default_
 * platform_plan), so a plain reason + confirm is enough; no typed
 * confirmation is needed here since none of these three actions touch
 * an organization's own data (unlike suspend/reactivate). */
export function PlanActionDialog({
  open,
  mode,
  planName,
  submitting,
  error,
  onClose,
  onConfirm,
}: PlanActionDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setReason("");
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

  const titleKey: Record<PlanActionMode, string> = {
    activate: "adminPlans.activateDialogTitle",
    deactivate: "adminPlans.deactivateDialogTitle",
    "make-default": "adminPlans.makeDefaultDialogTitle",
  };
  const descriptionKey: Record<PlanActionMode, string> = {
    activate: "adminPlans.activateDialogDescription",
    deactivate: "adminPlans.deactivateDialogDescription",
    "make-default": "adminPlans.makeDefaultDialogDescription",
  };
  const confirmLabelKey: Record<PlanActionMode, string> = {
    activate: "adminPlans.activateConfirmButton",
    deactivate: "adminPlans.deactivateConfirmButton",
    "make-default": "adminPlans.makeDefaultConfirmButton",
  };
  const title = t(titleKey[mode], { name: planName });
  const description = t(descriptionKey[mode], { name: planName });
  const confirmLabel = t(confirmLabelKey[mode]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        <p className="mt-1 text-xs text-slate-500">{description}</p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label htmlFor="plan-action-reason" className="text-xs font-medium text-slate-600">
              {t("admin.reasonLabel")}
            </label>
            <Textarea
              id="plan-action-reason"
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
            <Button type="submit" variant={mode === "deactivate" ? "danger" : "primary"} disabled={!canSubmit}>
              {submitting ? t("common.saving") : confirmLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
