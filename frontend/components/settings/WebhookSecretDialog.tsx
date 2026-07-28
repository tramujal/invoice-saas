"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";

type WebhookSecretDialogProps = {
  /** The complete signing secret, or null when there's nothing to show. */
  secret: string | null;
  onClose: () => void;
};

/** Shown exactly once, right after create/rotate-secret -- mirrors
 * ApiKeySecretDialog exactly (see that component's own docstring for the
 * full rationale). The one difference from an API key: this value IS
 * technically recoverable server-side later (see WebhookEndpoint.secret's
 * docstring in app/models.py -- the server must keep signing future
 * deliveries with it), but the application never exposes it back to the
 * browser again after this dialog closes -- there is no "reveal"
 * endpoint on the frontend-facing surface either. */
export function WebhookSecretDialog({ secret, onClose }: WebhookSecretDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => setMounted(true), []);
  useEffect(() => setCopied(false), [secret]);

  useEffect(() => {
    if (!secret) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [secret, onClose]);

  if (!secret || !mounted) return null;

  async function handleCopy() {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
    } catch {
      // Clipboard permission denied or unavailable -- the secret is
      // still selectable/readable in the <code> block below.
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={t("webhooks.secretDialogTitle")}
        className="w-full max-w-lg rounded-2xl border border-amber-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("webhooks.secretDialogTitle")}</h2>
        <p className="mt-2 text-sm text-slate-600">{t("webhooks.secretDialogMessage")}</p>

        <div className="mt-4 flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
          <code className="min-w-0 flex-1 select-all break-all font-mono text-xs text-slate-800">{secret}</code>
          <Button type="button" variant="secondary" size="sm" onClick={() => void handleCopy()}>
            {copied ? t("webhooks.secretDialogCopied") : t("webhooks.secretDialogCopyButton")}
          </Button>
        </div>

        <div className="mt-4 flex justify-end">
          <Button type="button" onClick={onClose}>
            {t("webhooks.secretDialogCloseButton")}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
