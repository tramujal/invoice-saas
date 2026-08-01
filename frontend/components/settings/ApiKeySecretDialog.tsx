"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";

type ApiKeySecretDialogProps = {
  /** The complete secret, or null when there's nothing to show. */
  apiKey: string | null;
  onClose: () => void;
};

/** Shown exactly once, right after create/rotate -- the only moment the
 * complete secret exists in the browser at all. There is no "reveal"
 * flow anywhere else: closing this dialog is the last time this value
 * is ever retrievable, matching the backend's own "only ever returned
 * once" contract (see OrganizationApiKey's docstring). */
export function ApiKeySecretDialog({ apiKey, onClose }: ApiKeySecretDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => setMounted(true), []);
  useEffect(() => setCopied(false), [apiKey]);

  useEffect(() => {
    if (!apiKey) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [apiKey, onClose]);

  if (!apiKey || !mounted) return null;

  async function handleCopy() {
    if (!apiKey) return;
    try {
      await navigator.clipboard.writeText(apiKey);
      setCopied(true);
    } catch {
      // Clipboard permission denied or unavailable -- the key is still
      // selectable/readable in the <code> block below, so this is a
      // non-fatal, silent fallback.
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={t("apiKeys.secretDialogTitle")}
        className="w-[calc(100vw-2rem)] max-w-lg rounded-2xl border border-amber-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("apiKeys.secretDialogTitle")}</h2>
        <p className="mt-2 text-sm text-slate-600">{t("apiKeys.secretDialogMessage")}</p>

        <div className="mt-4 flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
          <code className="min-w-0 flex-1 select-all break-all font-mono text-xs text-slate-800">{apiKey}</code>
          <Button type="button" variant="secondary" size="sm" onClick={() => void handleCopy()}>
            {copied ? t("apiKeys.secretDialogCopied") : t("apiKeys.secretDialogCopyButton")}
          </Button>
        </div>

        <div className="mt-4 flex justify-end">
          <Button type="button" onClick={onClose}>
            {t("apiKeys.secretDialogCloseButton")}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
