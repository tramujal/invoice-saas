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
};

/** Shown when PATCH /admin/settings returns 409
 * platform_settings_version_conflict -- another admin saved a change
 * after this page's data was loaded. Never fixes anything on its own:
 * the user's own unsaved draft is left exactly as they had it (see
 * PlatformSettingsPage's conflict handler, which never touches
 * draft/data itself on a 409), and "Reload latest settings" is the one
 * explicit action that discards it -- there is no automatic retry and
 * no silent merge anywhere in this flow. */
export function VersionConflictDialog({ open, reloading, onReload, onCancel }: VersionConflictDialogProps) {
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
        aria-label={t("admin.versionConflictTitle")}
        className="w-full max-w-md rounded-2xl border border-amber-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("admin.versionConflictTitle")}</h2>
        <p className="mt-2 text-sm text-slate-600">{t("admin.versionConflictMessage")}</p>

        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onCancel} disabled={reloading}>
            {t("admin.versionConflictCancelButton")}
          </Button>
          <Button type="button" onClick={onReload} disabled={reloading}>
            {reloading ? t("common.refreshing") : t("admin.versionConflictReloadButton")}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
