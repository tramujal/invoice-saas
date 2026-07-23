"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformSettingsUpdateRequest } from "@/lib/types";

export type SettingsFieldChange = {
  field: keyof Omit<PlatformSettingsUpdateRequest, "reason" | "expected_version">;
  label: string;
  oldDisplay: string;
  newDisplay: string;
  /** True when this specific change (not just the field) is one the
   * spec calls out for explicit warning copy -- enabling maintenance
   * mode, or disabling registrations/AI/email/reminders. Changing a
   * default language/currency, or turning a switch back ON, is a
   * routine change with no special copy. */
  warningKey: string | null;
};

type SettingsChangeDialogProps = {
  open: boolean;
  changes: SettingsFieldChange[];
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (reason: string) => void;
};

/** Confirmation dialog for PATCH /admin/settings -- always shown before
 * a save takes effect (never optimistic), always requires a reason (the
 * backend rejects a blank one), and surfaces the exact per-field warning
 * copy the spec calls for whenever a change in the diff is one of the
 * "major platform capability" toggles. Mirrors SuspendReactivateDialog's
 * portal/Escape/backdrop-click shape, but confirms a batch of field
 * changes rather than a single typed name. */
export function SettingsChangeDialog({
  open,
  changes,
  submitting,
  error,
  onClose,
  onConfirm,
}: SettingsChangeDialogProps) {
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
  const canSubmit = reasonValid && !submitting && changes.length > 0;
  const warnings = changes
    .map((change) => change.warningKey)
    .filter((key): key is string => key !== null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onConfirm(reason.trim());
  }

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
        aria-label={t("admin.settingsChangeDialogTitle")}
        className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("admin.settingsChangeDialogTitle")}</h2>
        <p className="mt-1 text-xs text-slate-500">{t("admin.settingsChangeDialogDescription")}</p>

        <ul className="mt-4 space-y-1.5 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
          {changes.map((change) => (
            <li key={change.field} className="flex items-center justify-between gap-3 text-slate-700">
              <span className="font-medium">{change.label}</span>
              <span className="text-right">
                <span className="text-slate-400 line-through">{change.oldDisplay}</span>{" "}
                <span className="font-semibold text-slate-900">{change.newDisplay}</span>
              </span>
            </li>
          ))}
        </ul>

        {warnings.length > 0 ? (
          <div
            className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800"
            role="alert"
          >
            <ul className="list-disc space-y-1 pl-4">
              {warnings.map((key) => (
                <li key={key}>{t(key)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label htmlFor="settings-change-reason" className="text-xs font-medium text-slate-600">
              {t("admin.reasonLabel")}
            </label>
            <Textarea
              id="settings-change-reason"
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
            <Button type="submit" variant={warnings.length > 0 ? "danger" : "primary"} disabled={!canSubmit}>
              {submitting ? t("common.saving") : t("admin.settingsChangeConfirmButton")}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
