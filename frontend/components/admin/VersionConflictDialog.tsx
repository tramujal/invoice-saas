"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";

type VersionConflictDialogProps = {
  open: boolean;
  reloading: boolean;
  onReload: () => void;
  onCancel: () => void;
  /** Defaults to the Platform Settings copy (this component's original,
   * still-only caller) -- other resources with their own optimistic
   * concurrency (e.g. Plans) pass their own i18n keys so the dialog
   * never says "settings" about something else. */
  titleKey?: string;
  messageKey?: string;
  reloadButtonKey?: string;
};

/** Shown whenever a versioned mutation returns its resource's own
 * "changed by someone else" 409 (platform_settings_version_conflict,
 * plan_version_conflict, ...) -- another admin saved a change after
 * this page's data was loaded. Never fixes anything on its own: the
 * user's own unsaved draft is left exactly as they had it (see each
 * caller's own conflict handler, which never touches its draft/data on
 * a 409), and "Reload latest" is the one explicit action that discards
 * it -- there is no automatic retry and no silent merge anywhere in
 * this flow. */
export function VersionConflictDialog({
  open,
  reloading,
  onReload,
  onCancel,
  titleKey = "admin.versionConflictTitle",
  messageKey = "admin.versionConflictMessage",
  reloadButtonKey = "admin.versionConflictReloadButton",
}: VersionConflictDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onCancel]);

  if (!open || !mounted) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={t(titleKey)}
        className="w-full max-w-md rounded-2xl border border-amber-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t(titleKey)}</h2>
        <p className="mt-2 text-sm text-slate-600">{t(messageKey)}</p>

        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onCancel} disabled={reloading}>
            {t("admin.versionConflictCancelButton")}
          </Button>
          <Button type="button" onClick={onReload} disabled={reloading}>
            {reloading ? t("common.refreshing") : t(reloadButtonKey)}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
