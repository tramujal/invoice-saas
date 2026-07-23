"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";

type Mode = "suspend" | "reactivate";

type SuspendReactivateDialogProps = {
  open: boolean;
  mode: Mode;
  organizationName: string;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (reason: string) => void;
};

/** Shared confirmation dialog for both destructive-adjacent organization
 * actions -- requires the exact organization name typed (never just a
 * click) plus a non-empty reason, mirrors the one existing modal in this
 * app (ManualLineEditor.tsx: portal, Escape-to-close, backdrop click).
 * Never optimistic -- onConfirm only fires once, the caller updates local
 * state from the mutation's own response, not before it arrives. */
export function SuspendReactivateDialog({
  open,
  mode,
  organizationName,
  submitting,
  error,
  onClose,
  onConfirm,
}: SuspendReactivateDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [reason, setReason] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setTypedName("");
    setReason("");
    nameInputRef.current?.focus();
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

  const nameMatches = typedName.trim() === organizationName;
  const reasonValid = reason.trim().length > 0;
  const canSubmit = nameMatches && reasonValid && !submitting;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onConfirm(reason.trim());
  }

  const title = mode === "suspend" ? t("admin.suspendDialogTitle") : t("admin.reactivateDialogTitle");
  const description =
    mode === "suspend" ? t("admin.suspendDialogDescription") : t("admin.reactivateDialogDescription");
  const confirmLabel =
    mode === "suspend" ? t("admin.suspendConfirmButton") : t("admin.reactivateConfirmButton");

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
            <label htmlFor="suspend-reactivate-org-name" className="text-xs font-medium text-slate-600">
              {t("admin.typeOrgNameLabel", { name: organizationName })}
            </label>
            <Input
              id="suspend-reactivate-org-name"
              ref={nameInputRef}
              type="text"
              value={typedName}
              onChange={(e) => setTypedName(e.target.value)}
              className="mt-1"
              disabled={submitting}
              autoComplete="off"
            />
          </div>

          <div>
            <label htmlFor="suspend-reactivate-reason" className="text-xs font-medium text-slate-600">
              {t("admin.reasonLabel")}
            </label>
            <Textarea
              id="suspend-reactivate-reason"
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
            <Button
              type="submit"
              variant={mode === "suspend" ? "danger" : "primary"}
              disabled={!canSubmit}
            >
              {submitting ? t("common.saving") : confirmLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
