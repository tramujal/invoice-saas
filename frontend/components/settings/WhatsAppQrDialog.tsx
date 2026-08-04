"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { WhatsAppQrResponse } from "@/lib/types";

type WhatsAppQrDialogProps = {
  /** The QR to display, or null when the dialog should be closed. Owned
   * by the parent -- this component never fetches on its own, since a
   * fresh QR is a mutating bridge call (POST /qr) the parent already
   * makes before opening this. */
  qr: WhatsAppQrResponse | null;
  onClose: () => void;
};

/** Shown only to callers with settings.manage -- the parent gates who can
 * ever reach the "Show QR" button that supplies `qr`. The QR image itself
 * is rendered from a base64 PNG payload the bridge/backend already
 * generated; nothing here talks to the bridge directly. */
export function WhatsAppQrDialog({ qr, onClose }: WhatsAppQrDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!qr) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [qr, onClose]);

  if (!qr || !mounted) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex animate-backdrop-in items-center justify-center bg-slate-900/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("whatsapp.qrDialogTitle")}
        className="w-[calc(100vw-2rem)] max-w-sm animate-modal-in rounded-2xl border border-slate-200 bg-white p-5 text-center shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("whatsapp.qrDialogTitle")}</h2>
        <p className="mt-2 text-sm text-slate-600">{t("whatsapp.qrDialogMessage")}</p>

        <div className="mx-auto mt-4 flex h-56 w-56 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 p-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- a
              one-off base64 PNG payload, not an optimizable static asset */}
          <img
            src={`data:image/png;base64,${qr.qr_data_base64}`}
            alt={t("whatsapp.qrDialogTitle")}
            className="h-full w-full"
          />
        </div>

        <p className="mt-3 text-xs text-slate-500">{t("whatsapp.qrDialogExpires")}</p>

        <div className="mt-4 flex justify-end">
          <Button type="button" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
