"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { AuditEntry } from "@/lib/types";

type AuditEntryDetailsDrawerProps = {
  entry: AuditEntry | null;
  onClose: () => void;
  eventTypeLabel: (eventType: string) => string;
  formatTimestamp: (value: string) => string;
};

function renderMetadataValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Read-only detail view for a single audit-timeline row -- mirrors
 * AuditLogEntryDrawer's exact shape (portal, Escape-to-close, plain-text
 * key/value rendering, never HTML), adapted to AuditEntry's own fields.
 * Not a reuse of that component directly since the two entry shapes
 * (platform-admin action vs. tenant domain event) share no fields beyond
 * created_at. */
export function AuditEntryDetailsDrawer({
  entry,
  onClose,
  eventTypeLabel,
  formatTimestamp,
}: AuditEntryDetailsDrawerProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!entry) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [entry, onClose]);

  if (!entry || !mounted) return null;

  const metadataEntries = entry.metadata ? Object.entries(entry.metadata) : [];

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-backdrop-in items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("settingsAuditLog.detailsTitle")}
        className="w-[calc(100vw-2rem)] max-w-lg animate-modal-in rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-sm font-semibold text-slate-900">{t("settingsAuditLog.detailsTitle")}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        <dl className="mt-4 max-h-[60vh] space-y-3 overflow-y-auto text-sm">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("settingsAuditLog.colTimestamp")}
            </dt>
            <dd className="text-slate-900">{formatTimestamp(entry.created_at)}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("settingsAuditLog.colEvent")}
            </dt>
            <dd className="text-slate-900" title={entry.event_type}>
              {eventTypeLabel(entry.event_type)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("settingsAuditLog.colActor")}
            </dt>
            <dd className="text-slate-900">{entry.actor_email ?? t("settingsAuditLog.systemActor")}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("settingsAuditLog.colResource")}
            </dt>
            <dd className="text-slate-900">
              {entry.resource_type} · {entry.resource_id}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("settingsAuditLog.detailsSectionTitle")}
            </dt>
            {metadataEntries.length === 0 ? (
              <dd className="text-slate-500">{t("settingsAuditLog.noDetails")}</dd>
            ) : (
              <dd>
                <ul className="mt-1 space-y-1 rounded-lg bg-surface-muted p-3">
                  {metadataEntries.map(([key, value]) => (
                    <li key={key} className="flex justify-between gap-4 text-xs">
                      <span className="shrink-0 font-medium text-slate-600">{key}</span>
                      {/* A metadata value can be an arbitrary JSON-
                          stringified blob, URL, or id with no spaces to
                          break at -- min-w-0 lets this flex item shrink
                          below its content's natural width, and
                          break-words/[overflow-wrap:anywhere] let long
                          unbroken runs actually wrap instead of forcing
                          this dialog (and everything behind it) wider
                          than the viewport. */}
                      <span className="min-w-0 flex-1 break-words text-right text-slate-900 [overflow-wrap:anywhere]">
                        {renderMetadataValue(value)}
                      </span>
                    </li>
                  ))}
                </ul>
              </dd>
            )}
          </div>
        </dl>

        <div className="mt-5 flex justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
