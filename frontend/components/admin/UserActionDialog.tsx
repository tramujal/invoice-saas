"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";

export type UserActionMode = "disable" | "enable" | "grant-role" | "revoke-role";

type UserActionDialogProps = {
  open: boolean;
  mode: UserActionMode;
  userEmail: string;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (reason: string) => void;
};

/** Shared confirmation dialog for the four platform user-management
 * actions that require typed confirmation + a written reason (disable,
 * enable, grant platform role, revoke platform role) -- structurally
 * identical to SuspendReactivateDialog (portal, Escape-to-close, backdrop
 * click, never optimistic), just confirming the user's email instead of
 * an organization name. Verify-email and send-password-reset are
 * deliberately NOT handled here -- see SimpleConfirmDialog for those
 * lower-friction actions, which the backend doesn't require a reason
 * for either. */
export function UserActionDialog({
  open,
  mode,
  userEmail,
  submitting,
  error,
  onClose,
  onConfirm,
}: UserActionDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [typedEmail, setTypedEmail] = useState("");
  const [reason, setReason] = useState("");
  const emailInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setTypedEmail("");
    setReason("");
    emailInputRef.current?.focus();
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

  const emailMatches = typedEmail.trim() === userEmail;
  const reasonValid = reason.trim().length > 0;
  const canSubmit = emailMatches && reasonValid && !submitting;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onConfirm(reason.trim());
  }

  const titleKey: Record<UserActionMode, string> = {
    disable: "admin.disableUserDialogTitle",
    enable: "admin.enableUserDialogTitle",
    "grant-role": "admin.grantRoleDialogTitle",
    "revoke-role": "admin.revokeRoleDialogTitle",
  };
  const descriptionKey: Record<UserActionMode, string> = {
    disable: "admin.disableUserDialogDescription",
    enable: "admin.enableUserDialogDescription",
    "grant-role": "admin.grantRoleDialogDescription",
    "revoke-role": "admin.revokeRoleDialogDescription",
  };
  const confirmLabelKey: Record<UserActionMode, string> = {
    disable: "admin.disableUserConfirmButton",
    enable: "admin.enableUserConfirmButton",
    "grant-role": "admin.grantRoleConfirmButton",
    "revoke-role": "admin.revokeRoleConfirmButton",
  };
  const title = t(titleKey[mode]);
  const description = t(descriptionKey[mode]);
  const confirmLabel = t(confirmLabelKey[mode]);
  const isDestructive = mode === "disable" || mode === "revoke-role";

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
            <label htmlFor="user-action-email" className="text-xs font-medium text-slate-600">
              {t("admin.typeUserEmailLabel", { email: userEmail })}
            </label>
            <Input
              id="user-action-email"
              ref={emailInputRef}
              type="text"
              value={typedEmail}
              onChange={(e) => setTypedEmail(e.target.value)}
              className="mt-1"
              disabled={submitting}
              autoComplete="off"
            />
          </div>

          <div>
            <label htmlFor="user-action-reason" className="text-xs font-medium text-slate-600">
              {t("admin.reasonLabel")}
            </label>
            <Textarea
              id="user-action-reason"
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
            <Button type="submit" variant={isDestructive ? "danger" : "primary"} disabled={!canSubmit}>
              {submitting ? t("common.saving") : confirmLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
