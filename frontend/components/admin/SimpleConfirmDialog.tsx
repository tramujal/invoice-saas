"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";

export type SimpleConfirmMode = "verify-email" | "send-password-reset";

type SimpleConfirmDialogProps = {
  open: boolean;
  mode: SimpleConfirmMode;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => void;
};

/** Lower-friction sibling of UserActionDialog -- verify-email and
 * send-password-reset don't collect a reason or typed confirmation on
 * the backend (see PlatformUserActionResponse-shaped endpoints in
 * app.routers.platform_admin), so this is a single confirm/cancel
 * click, not a form. Never renders a token, hash, or reset link -- the
 * description text explicitly says so for send-password-reset, matching
 * the requirement that no password/secret is ever visible to the
 * administrator. */
export function SimpleConfirmDialog({
  open,
  mode,
  submitting,
  error,
  onClose,
  onConfirm,
}: SimpleConfirmDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

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

  const title = mode === "verify-email" ? t("admin.verifyEmailDialogTitle") : t("admin.sendResetDialogTitle");
  const description =
    mode === "verify-email" ? t("admin.verifyEmailDialogDescription") : t("admin.sendResetDialogDescription");
  const confirmLabel =
    mode === "verify-email" ? t("admin.verifyEmailConfirmButton") : t("admin.sendResetConfirmButton");

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

        {error ? (
          <p className="mt-4 text-xs text-red-700" role="alert">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button type="button" onClick={onConfirm} disabled={submitting}>
            {submitting ? t("common.saving") : confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
