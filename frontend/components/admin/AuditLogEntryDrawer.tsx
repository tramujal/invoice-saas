"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformAuditLogEntry } from "@/lib/types";

type AuditLogEntryDrawerProps = {
  entry: PlatformAuditLogEntry | null;
  onClose: () => void;
  actionLabel: (code: string) => string;
  formatTimestamp: (value: string) => string;
};

function renderDetailValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Read-only detail view for a single audit-log row -- every value here
 * is already sanitized server-side (see app.platform_audit_sanitize)
 * before it ever reaches this component; this only renders it as plain
 * text key/value pairs, never as HTML, so there's no second place a
 * secret-shaped value could leak even if sanitization ever regressed. */
export function AuditLogEntryDrawer({ entry, onClose, actionLabel, formatTimestamp }: AuditLogEntryDrawerProps) {
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

  const targetLabel =
    entry.target_type === "organization"
      ? (entry.target_organization_name ?? "—")
      : entry.target_type === "user"
        ? (entry.target_user_email ?? "—")
        : "—";

  const detailEntries = entry.details ? Object.entries(entry.details) : [];

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("auditLog.detailsTitle")}
        className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-sm font-semibold text-slate-900">{t("auditLog.detailsTitle")}</h2>
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
              {t("auditLog.colTimestamp")}
            </dt>
            <dd className="text-slate-900">{formatTimestamp(entry.created_at)}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("auditLog.colAction")}
            </dt>
            <dd className="text-slate-900" title={entry.action}>
              {actionLabel(entry.action)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("auditLog.colActor")}
            </dt>
            <dd className="text-slate-900">{entry.actor_email}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("auditLog.colTarget")}
            </dt>
            <dd className="text-slate-900">{targetLabel}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("auditLog.colReason")}
            </dt>
            <dd className="whitespace-pre-wrap text-slate-900">{entry.reason}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{t("auditLog.colIp")}</dt>
            <dd className="text-slate-900">{entry.client_ip ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {t("auditLog.detailsSectionTitle")}
            </dt>
            {detailEntries.length === 0 ? (
              <dd className="text-slate-500">{t("auditLog.noDetails")}</dd>
            ) : (
              <dd>
                <ul className="mt-1 space-y-1 rounded-lg bg-surface-muted p-3">
                  {detailEntries.map(([key, value]) => (
                    <li key={key} className="flex justify-between gap-4 text-xs">
                      <span className="font-medium text-slate-600">{key}</span>
                      <span className="text-right text-slate-900">{renderDetailValue(value)}</span>
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
