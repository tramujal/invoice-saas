"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlanLimitReachedDetail, PlanLimitReachedResource } from "@/lib/types";

// Reuses the exact row labels already shown on the tenant Plan & Limits
// page (frontend/app/(dashboard)/settings/plan/page.tsx) -- one place
// defines what each resource is called, so this dialog and that page can
// never drift apart on terminology.
const RESOURCE_LABEL_KEY: Record<PlanLimitReachedResource, string> = {
  users: "planAndLimits.rowUsers",
  customers: "planAndLimits.rowCustomers",
  products: "planAndLimits.rowProducts",
  invoices: "planAndLimits.rowInvoices",
  quotes: "planAndLimits.rowQuotes",
  ai_actions: "planAndLimits.rowAiActions",
};

type PlanLimitReachedDialogProps = {
  detail: PlanLimitReachedDetail | null;
  onClose: () => void;
};

/** Shown whenever a create/restore/accept-invitation/AI-action call
 * returns the structured 409 plan_limit_reached (see
 * app.services.plan_limits.PlanLimitExceededError). Deliberately shows
 * only Used/Limit/Current plan -- no pricing, no "Upgrade" button, no
 * payment UI of any kind, since billing/upgrade flows don't exist yet
 * (Phase 14C scope). The backend's own `message` string is never
 * rendered; every field shown here comes from the structured detail. */
export function PlanLimitReachedDialog({ detail, onClose }: PlanLimitReachedDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!detail) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [detail, onClose]);

  if (!detail || !mounted) return null;

  const resourceLabel = t(RESOURCE_LABEL_KEY[detail.resource]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={t("planLimitReached.title")}
        className="w-full max-w-md rounded-2xl border border-amber-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("planLimitReached.title")}</h2>
        <p className="mt-2 text-sm text-slate-600">
          {t("planLimitReached.message", { resource: resourceLabel })}
        </p>

        <dl className="mt-4 space-y-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
          <div className="flex items-center justify-between">
            <dt className="text-slate-500">{resourceLabel}</dt>
            <dd className="font-medium text-slate-900">
              {detail.used.toLocaleString()} / {detail.limit.toLocaleString()}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="text-slate-500">{t("planAndLimits.currentPlanLabel")}</dt>
            <dd className="font-medium text-slate-900">{detail.plan.name}</dd>
          </div>
        </dl>

        <div className="mt-4 flex justify-end">
          <Button type="button" onClick={onClose}>
            {t("planLimitReached.closeButton")}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
