"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Plan } from "@/lib/types";

type OrganizationPlanChangeDialogProps = {
  open: boolean;
  organizationName: string;
  currentPlanId: string;
  plans: Plan[];
  loadingPlans: boolean;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (planId: string, reason: string) => void;
};

/** Same typed-confirmation + mandatory-reason shape as
 * SuspendReactivateDialog (type the exact organization name, plus a
 * non-blank reason) -- changing which plan an organization is on is
 * exactly the kind of consequential, easy-to-misclick action that
 * precedent already exists for in this app. Only active plans are
 * offered (see the `plans` prop, already filtered by the caller) since
 * an inactive plan can never be newly assigned -- the backend enforces
 * this too, but there's no reason to let an admin pick a choice that
 * would only bounce back as an error. */
export function OrganizationPlanChangeDialog({
  open,
  organizationName,
  currentPlanId,
  plans,
  loadingPlans,
  submitting,
  error,
  onClose,
  onConfirm,
}: OrganizationPlanChangeDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [reason, setReason] = useState("");
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setTypedName("");
    setReason("");
    setSelectedPlanId("");
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
  const planSelected = selectedPlanId !== "" && selectedPlanId !== currentPlanId;
  const canSubmit = nameMatches && reasonValid && planSelected && !submitting;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onConfirm(selectedPlanId, reason.trim());
  }

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
        aria-label={t("adminPlans.changePlanDialogTitle")}
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("adminPlans.changePlanDialogTitle")}</h2>
        <p className="mt-1 text-xs text-slate-500">{t("adminPlans.changePlanDialogDescription")}</p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label htmlFor="change-plan-select" className="text-xs font-medium text-slate-600">
              {t("adminPlans.selectNewPlanLabel")}
            </label>
            <Select
              id="change-plan-select"
              value={selectedPlanId}
              onChange={(e) => setSelectedPlanId(e.target.value)}
              className="mt-1"
              disabled={submitting || loadingPlans}
            >
              <option value="">{t("adminPlans.selectNewPlanPlaceholder")}</option>
              {plans
                .filter((plan) => plan.id !== currentPlanId)
                .map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.name}
                  </option>
                ))}
            </Select>
          </div>

          <div>
            <label htmlFor="change-plan-org-name" className="text-xs font-medium text-slate-600">
              {t("admin.typeOrgNameLabel", { name: organizationName })}
            </label>
            <Input
              id="change-plan-org-name"
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
            <label htmlFor="change-plan-reason" className="text-xs font-medium text-slate-600">
              {t("admin.reasonLabel")}
            </label>
            <Textarea
              id="change-plan-reason"
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
            <Button type="submit" disabled={!canSubmit}>
              {submitting ? t("common.saving") : t("adminPlans.changePlanConfirmButton")}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
