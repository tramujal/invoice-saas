"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { CustomerDuplicateCheckResponse } from "@/lib/types";

const REASON_LABEL_KEY: Record<string, string> = {
  tax_id: "customerDuplicate.reasonTaxId",
  email: "customerDuplicate.reasonEmail",
  phone: "customerDuplicate.reasonPhone",
  name: "customerDuplicate.reasonName",
};

type CustomerDuplicateDialogProps = {
  /** Only "warning" (Level 2/3 -- email/phone) and "blocking" (Level 1 --
   * tax_id) ever render a dialog; "none" and "suggestion" (Level 4 --
   * name) resolve to null here on purpose -- see CustomerForm's own
   * duplicate-check branch, which never opens this component for those
   * two severities in the first place. */
  result: CustomerDuplicateCheckResponse | null;
  submitting?: boolean;
  onCancel: () => void;
  onCreateAnyway: () => void;
  onOpenExisting: (customerId: string) => void;
  /** Overrides the default "Create anyway" label -- CustomerForm passes
   * "Save anyway" when editing an existing customer instead of creating
   * a new one. */
  createAnywayLabel?: string;
};

/** Phase UX5's duplicate-customer confirmation dialog. Same portal/
 * animation/Escape shape as PlanLimitReachedDialog and SimpleConfirmDialog
 * (Phase UX4). Default focus is always Cancel (native `autoFocus`, since
 * Button isn't a forwardRef component) -- required behavior, not a
 * stylistic choice: "Create anyway" must never be the path of least
 * resistance. The "blocking" variant (tax_id) never renders a
 * "Create anyway" button at all -- there is no bypass for that level. */
export function CustomerDuplicateDialog({
  result,
  submitting = false,
  onCancel,
  onCreateAnyway,
  onOpenExisting,
  createAnywayLabel,
}: CustomerDuplicateDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const open = Boolean(result && (result.severity === "warning" || result.severity === "blocking"));

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

  if (!result || !mounted || !open) return null;

  const isBlocking = result.severity === "blocking";
  const title = t(isBlocking ? "customerDuplicate.blockingTitle" : "customerDuplicate.warningTitle");
  const reasonLabel = (reason: string) => t(REASON_LABEL_KEY[reason] ?? reason);
  const allReasons = Array.from(new Set(result.matches.flatMap((m) => m.reasons)));
  const message = isBlocking
    ? t("customerDuplicate.blockingMessage")
    : t("customerDuplicate.warningMessage", { reasons: allReasons.map(reasonLabel).join(", ") });

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-backdrop-in items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !submitting) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-lg animate-modal-in rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        <p className="mt-1 text-sm text-slate-600">{message}</p>

        <ul className="mt-4 max-h-64 space-y-2 overflow-y-auto">
          {result.matches.map((match) => (
            <li
              key={match.customer_id}
              className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-900">{match.customer_name}</p>
                  <dl className="mt-1 space-y-0.5 text-xs text-slate-600">
                    {match.email ? (
                      <div className="truncate">
                        <dt className="inline font-medium text-slate-500">{t("common.email")}: </dt>
                        <dd className="inline">{match.email}</dd>
                      </div>
                    ) : null}
                    {match.phone ? (
                      <div className="truncate">
                        <dt className="inline font-medium text-slate-500">{t("common.phone")}: </dt>
                        <dd className="inline">{match.phone}</dd>
                      </div>
                    ) : null}
                    {match.tax_id ? (
                      <div className="truncate">
                        <dt className="inline font-medium text-slate-500">
                          {t("customers.taxIdLabel")}:{" "}
                        </dt>
                        <dd className="inline">{match.tax_id}</dd>
                      </div>
                    ) : null}
                  </dl>
                  <p className="mt-1 text-xs text-slate-500">
                    {t("customerDuplicate.reasonsLabel")}: {match.reasons.map(reasonLabel).join(", ")}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="shrink-0"
                  onClick={() => onOpenExisting(match.customer_id)}
                >
                  {t("customerDuplicate.openExistingButton")}
                </Button>
              </div>
            </li>
          ))}
        </ul>

        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            type="button"
            variant="secondary"
            onClick={onCancel}
            disabled={submitting}
            autoFocus
          >
            {t("common.cancel")}
          </Button>
          {isBlocking ? null : (
            <Button type="button" onClick={onCreateAnyway} disabled={submitting} loading={submitting}>
              {createAnywayLabel ?? t("customerDuplicate.createAnywayButton")}
            </Button>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
