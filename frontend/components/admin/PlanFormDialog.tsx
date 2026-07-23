"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Plan, PlanCreateRequest, PlanUpdateRequest } from "@/lib/types";

type LimitFieldKey =
  | "max_users"
  | "max_customers"
  | "max_products"
  | "max_invoices_per_month"
  | "max_quotes_per_month"
  | "max_ai_actions_per_month"
  | "storage_limit_mb";

const LIMIT_FIELDS: { key: LimitFieldKey; labelKey: string }[] = [
  { key: "max_users", labelKey: "adminPlans.limitMaxUsers" },
  { key: "max_customers", labelKey: "adminPlans.limitMaxCustomers" },
  { key: "max_products", labelKey: "adminPlans.limitMaxProducts" },
  { key: "max_invoices_per_month", labelKey: "adminPlans.limitMaxInvoices" },
  { key: "max_quotes_per_month", labelKey: "adminPlans.limitMaxQuotes" },
  { key: "max_ai_actions_per_month", labelKey: "adminPlans.limitMaxAiActions" },
  { key: "storage_limit_mb", labelKey: "adminPlans.limitStorageMb" },
];

type FeatureFieldKey = "custom_branding_enabled" | "api_access_enabled" | "advanced_reports_enabled";

const FEATURE_FIELDS: { key: FeatureFieldKey; labelKey: string }[] = [
  { key: "custom_branding_enabled", labelKey: "adminPlans.featureCustomBranding" },
  { key: "api_access_enabled", labelKey: "adminPlans.featureApiAccess" },
  { key: "advanced_reports_enabled", labelKey: "adminPlans.featureAdvancedReports" },
];

type FormValues = {
  code: string;
  name: string;
  description: string;
  sort_order: string;
} & Record<LimitFieldKey, string> & Record<FeatureFieldKey, boolean>;

function valuesFromPlan(plan: Plan | null): FormValues {
  const limits: Record<LimitFieldKey, string> = {
    max_users: plan?.limits.max_users?.toString() ?? "",
    max_customers: plan?.limits.max_customers?.toString() ?? "",
    max_products: plan?.limits.max_products?.toString() ?? "",
    max_invoices_per_month: plan?.limits.max_invoices_per_month?.toString() ?? "",
    max_quotes_per_month: plan?.limits.max_quotes_per_month?.toString() ?? "",
    max_ai_actions_per_month: plan?.limits.max_ai_actions_per_month?.toString() ?? "",
    storage_limit_mb: plan?.limits.storage_limit_mb?.toString() ?? "",
  };
  return {
    code: plan?.code ?? "",
    name: plan?.name ?? "",
    description: plan?.description ?? "",
    sort_order: (plan?.sort_order ?? 0).toString(),
    ...limits,
    custom_branding_enabled: plan?.features.custom_branding_enabled ?? false,
    api_access_enabled: plan?.features.api_access_enabled ?? false,
    advanced_reports_enabled: plan?.features.advanced_reports_enabled ?? false,
  };
}

/** Blank string = unlimited (null), "0" = unavailable, any other
 * non-negative integer = a hard limit -- matches app.models.Plan's own
 * NULL/0/positive-integer convention exactly, so the admin never has to
 * remember which sentinel means what. */
function parseLimit(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : null;
}

type PlanFormDialogProps = {
  open: boolean;
  mode: "create" | "edit";
  plan: Plan | null;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onSubmitCreate: (body: PlanCreateRequest) => void;
  onSubmitEdit: (body: PlanUpdateRequest) => void;
};

/** The one modal both "Create plan" and "Edit plan" use -- create sends
 * every field (a brand-new plan should be fully specified, matching the
 * four seeded plans), edit only sends fields the admin actually changed
 * (see handleSubmit's diff against the plan's original values), which is
 * what lets PATCH's own no-op/empty-update checks work as designed. Code
 * is only ever shown, never editable, in edit mode -- immutability is
 * enforced by the backend not accepting the field at all, but hiding the
 * input here means there's nothing to misleadingly type into. */
export function PlanFormDialog({
  open,
  mode,
  plan,
  submitting,
  error,
  onClose,
  onSubmitCreate,
  onSubmitEdit,
}: PlanFormDialogProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [values, setValues] = useState<FormValues>(() => valuesFromPlan(plan));
  const [reason, setReason] = useState("");

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    setValues(valuesFromPlan(plan));
    setReason("");
  }, [open, plan]);

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

  function update<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  const codeValid = mode === "edit" || /^[a-z0-9_-]+$/.test(values.code.trim());
  const nameValid = values.name.trim().length > 0;
  const reasonValid = reason.trim().length > 0;
  const canSubmit = codeValid && nameValid && reasonValid && !submitting;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    const limitValues = Object.fromEntries(
      LIMIT_FIELDS.map(({ key }) => [key, parseLimit(values[key])])
    ) as Record<LimitFieldKey, number | null>;
    const featureValues = Object.fromEntries(
      FEATURE_FIELDS.map(({ key }) => [key, values[key]])
    ) as Record<FeatureFieldKey, boolean>;

    if (mode === "create") {
      onSubmitCreate({
        code: values.code.trim(),
        name: values.name.trim(),
        description: values.description.trim() || null,
        sort_order: Number(values.sort_order) || 0,
        ...limitValues,
        ...featureValues,
        reason: reason.trim(),
      });
      return;
    }

    onSubmitEdit({
      reason: reason.trim(),
      expected_version: plan?.version ?? 0,
      name: values.name.trim(),
      description: values.description.trim() || null,
      sort_order: Number(values.sort_order) || 0,
      ...limitValues,
      ...featureValues,
    });
  }

  const title = mode === "create" ? t("adminPlans.createDialogTitle") : t("adminPlans.editDialogTitle", { name: plan?.name ?? "" });

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
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>

        <form onSubmit={handleSubmit} className="mt-4 space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            {mode === "create" ? (
              <div>
                <label htmlFor="plan-code" className="text-xs font-medium text-slate-600">
                  {t("adminPlans.fieldCode")}
                </label>
                <Input
                  id="plan-code"
                  value={values.code}
                  onChange={(e) => update("code", e.target.value)}
                  className="mt-1"
                  disabled={submitting}
                  autoComplete="off"
                  placeholder="starter-plus"
                />
              </div>
            ) : (
              <div>
                <span className="text-xs font-medium text-slate-600">{t("adminPlans.fieldCode")}</span>
                <p className="mt-1 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2.5 text-sm text-slate-500">
                  {plan?.code}
                </p>
              </div>
            )}
            <div>
              <label htmlFor="plan-name" className="text-xs font-medium text-slate-600">
                {t("adminPlans.fieldName")}
              </label>
              <Input
                id="plan-name"
                value={values.name}
                onChange={(e) => update("name", e.target.value)}
                className="mt-1"
                disabled={submitting}
              />
            </div>
          </div>

          <div>
            <label htmlFor="plan-description" className="text-xs font-medium text-slate-600">
              {t("adminPlans.fieldDescription")}
            </label>
            <Textarea
              id="plan-description"
              value={values.description}
              onChange={(e) => update("description", e.target.value)}
              rows={2}
              className="mt-1 resize-none"
              disabled={submitting}
            />
          </div>

          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {t("adminPlans.sectionLimits")}
            </h3>
            <p className="mt-0.5 text-xs text-slate-400">{t("adminPlans.limitsHint")}</p>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              {LIMIT_FIELDS.map(({ key, labelKey }) => (
                <div key={key}>
                  <label htmlFor={`plan-${key}`} className="text-xs font-medium text-slate-600">
                    {t(labelKey)}
                  </label>
                  <Input
                    id={`plan-${key}`}
                    type="number"
                    min={0}
                    inputMode="numeric"
                    value={values[key]}
                    onChange={(e) => update(key, e.target.value)}
                    className="mt-1"
                    disabled={submitting}
                    placeholder={t("adminPlans.unlimitedPlaceholder")}
                  />
                </div>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {t("adminPlans.sectionFeatures")}
            </h3>
            <div className="mt-2 space-y-2">
              {FEATURE_FIELDS.map(({ key, labelKey }) => (
                <label key={key} className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={values[key]}
                    onChange={(e) => update(key, e.target.checked)}
                    disabled={submitting}
                    className="h-4 w-4 rounded border-slate-300"
                  />
                  {t(labelKey)}
                </label>
              ))}
            </div>
          </div>

          <div>
            <label htmlFor="plan-form-reason" className="text-xs font-medium text-slate-600">
              {t("admin.reasonLabel")}
            </label>
            <Textarea
              id="plan-form-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
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
              {submitting
                ? t("common.saving")
                : mode === "create"
                  ? t("adminPlans.createConfirmButton")
                  : t("adminPlans.editConfirmButton")}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
