"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { PlanActionDialog, type PlanActionMode } from "@/components/admin/PlanActionDialog";
import { PlanFormDialog } from "@/components/admin/PlanFormDialog";
import { VersionConflictDialog } from "@/components/admin/VersionConflictDialog";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  TABLE_BODY_CLASS,
  TABLE_CELL_CLASS,
  TABLE_CLASS,
  TABLE_HEAD_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_WRAPPER_CLASS,
} from "@/components/ui/TableShell";
import { RowActionsMenu, STICKY_ACTIONS_TD_CLASS, STICKY_ACTIONS_TH_CLASS } from "@/components/ui/RowActionsMenu";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch } from "@/lib/api";
import { formatApiError, getApiErrorCode } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatPlanLimit } from "@/lib/plan-limits";
import type { Plan, PlanCreateRequest, PlanUpdateRequest, PlansListResponse } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

/** Which open dialog a plan_version_conflict 409 was raised from -- lets
 * "Reload latest" know both which plan id to re-fetch and which
 * underlying dialog's local state to refresh in place, without closing
 * it (matching VersionConflictDialog's "never silently overwrite an
 * unsaved draft, only an explicit Reload does that" contract). */
type ConflictSource = "edit" | PlanActionMode;

export default function PlatformPlansPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [editingPlan, setEditingPlan] = useState<Plan | null>(null);
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [actionPlan, setActionPlan] = useState<Plan | null>(null);
  const [actionMode, setActionMode] = useState<PlanActionMode | null>(null);
  const [actionSubmitting, setActionSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [conflictSource, setConflictSource] = useState<ConflictSource | null>(null);
  const [conflictReloading, setConflictReloading] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const json = await apiFetch<PlansListResponse>("/admin/plans", { signal: controller.signal });
      setPlans(json.items);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setPlans(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  function replacePlan(updated: Plan) {
    setPlans((prev) => {
      if (!prev) return prev;
      const isNew = !prev.some((p) => p.id === updated.id);
      const next = isNew ? [...prev, updated] : prev.map((p) => (p.id === updated.id ? updated : p));
      return next.sort((a, b) => a.sort_order - b.sort_order);
    });
  }

  async function handleCreate(body: PlanCreateRequest) {
    setFormSubmitting(true);
    setFormError(null);
    try {
      const created = await apiFetch<Plan>("/admin/plans", { method: "POST", body: JSON.stringify(body) });
      replacePlan(created);
      setFormOpen(false);
      toast.success(t("adminPlans.createdToast"));
    } catch (e) {
      setFormError(e instanceof ApiError ? formatApiError(e, t("admin.mutationErrorGeneric")) : t("admin.mutationErrorGeneric"));
    } finally {
      setFormSubmitting(false);
    }
  }

  async function handleEdit(body: PlanUpdateRequest) {
    if (!editingPlan) return;
    setFormSubmitting(true);
    setFormError(null);
    try {
      const updated = await apiFetch<Plan>(`/admin/plans/${editingPlan.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      replacePlan(updated);
      setFormOpen(false);
      toast.success(t("adminPlans.updatedToast"));
    } catch (e) {
      if (getApiErrorCode(e) === "plan_version_conflict") {
        setConflictSource("edit");
        return;
      }
      setFormError(e instanceof ApiError ? formatApiError(e, t("admin.mutationErrorGeneric")) : t("admin.mutationErrorGeneric"));
    } finally {
      setFormSubmitting(false);
    }
  }

  async function handleAction(reason: string) {
    if (!actionPlan || !actionMode) return;
    setActionSubmitting(true);
    setActionError(null);
    try {
      const path =
        actionMode === "make-default"
          ? `/admin/plans/${actionPlan.id}/make-default`
          : `/admin/plans/${actionPlan.id}/${actionMode}`;
      const updated = await apiFetch<Plan>(path, {
        method: "POST",
        body: JSON.stringify({ reason, expected_version: actionPlan.version }),
      });
      replacePlan(updated);
      // make-default also flips the previous default's own row -- a
      // full reload is the simplest way to reflect that second,
      // server-side side effect without duplicating its logic here.
      if (actionMode === "make-default") void load();
      setActionPlan(null);
      setActionMode(null);
      const toastKey =
        actionMode === "activate"
          ? "adminPlans.activatedToast"
          : actionMode === "deactivate"
            ? "adminPlans.deactivatedToast"
            : "adminPlans.makeDefaultToast";
      toast.success(t(toastKey));
    } catch (e) {
      if (getApiErrorCode(e) === "plan_version_conflict") {
        setConflictSource(actionMode);
        return;
      }
      setActionError(e instanceof ApiError ? formatApiError(e, t("admin.mutationErrorGeneric")) : t("admin.mutationErrorGeneric"));
    } finally {
      setActionSubmitting(false);
    }
  }

  async function handleReloadLatestPlan() {
    const planId = conflictSource === "edit" ? editingPlan?.id : actionPlan?.id;
    if (!planId) {
      setConflictSource(null);
      return;
    }
    setConflictReloading(true);
    try {
      const fresh = await apiFetch<Plan>(`/admin/plans/${planId}`);
      replacePlan(fresh);
      if (conflictSource === "edit") {
        setEditingPlan(fresh);
      } else {
        setActionPlan(fresh);
      }
      setConflictSource(null);
    } catch {
      // Leave the conflict dialog open -- the admin can retry "Reload
      // latest" or fall back to "Keep editing" to discard the whole
      // attempt; there is nothing more automatic to do here.
    } finally {
      setConflictReloading(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        title={t("adminPlans.title")}
        subtitle={t("adminPlans.subtitle")}
        actions={
          <Button
            type="button"
            size="sm"
            onClick={() => {
              setFormMode("create");
              setEditingPlan(null);
              setFormError(null);
              setFormOpen(true);
            }}
          >
            {t("adminPlans.createButton")}
          </Button>
        }
      />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">{t("adminPlans.loading")}</p>
      ) : !plans || plans.length === 0 ? (
        <EmptyState title={t("adminPlans.emptyTitle")} description={t("adminPlans.emptyDescription")} />
      ) : (
        <div className={TABLE_WRAPPER_CLASS}>
          <div className="overflow-x-auto">
            <table className={TABLE_CLASS}>
              <thead className={TABLE_HEAD_CLASS}>
                <tr>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("adminPlans.colPlan")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("adminPlans.colStatus")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("adminPlans.colUsers")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("adminPlans.colCustomers")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("adminPlans.colStorage")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("adminPlans.colFeatures")}</th>
                  <th className={STICKY_ACTIONS_TH_CLASS}>
                    <span className="sr-only">{t("common.moreActions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody className={TABLE_BODY_CLASS}>
                {plans.map((plan) => (
                  <tr key={plan.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>
                      <div className="font-medium text-slate-900">{plan.name}</div>
                      <div className="text-xs text-slate-500">{plan.code}</div>
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <div className="flex flex-wrap gap-1.5">
                        <Badge
                          className={
                            plan.is_active
                              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                              : "bg-slate-100 text-slate-600 ring-slate-200"
                          }
                        >
                          {plan.is_active ? t("adminPlans.statusActive") : t("adminPlans.statusInactive")}
                        </Badge>
                        {plan.is_default ? (
                          <Badge className="bg-sky-50 text-sky-700 ring-sky-200">{t("adminPlans.statusDefault")}</Badge>
                        ) : null}
                      </div>
                    </td>
                    <td className={TABLE_CELL_CLASS}>{formatPlanLimit(plan.limits.max_users, t)}</td>
                    <td className={TABLE_CELL_CLASS}>{formatPlanLimit(plan.limits.max_customers, t)}</td>
                    <td className={TABLE_CELL_CLASS}>
                      {plan.limits.storage_limit_mb === null
                        ? t("planLimits.unlimited")
                        : plan.limits.storage_limit_mb === 0
                          ? t("planLimits.unavailable")
                          : t("adminPlans.storageMbValue", { mb: plan.limits.storage_limit_mb })}
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <div className="flex flex-wrap gap-1">
                        {plan.features.custom_branding_enabled ? (
                          <Badge className="bg-violet-50 text-violet-700 ring-violet-200">
                            {t("adminPlans.featureCustomBrandingShort")}
                          </Badge>
                        ) : null}
                        {plan.features.api_access_enabled ? (
                          <Badge className="bg-violet-50 text-violet-700 ring-violet-200">
                            {t("adminPlans.featureApiAccessShort")}
                          </Badge>
                        ) : null}
                        {plan.features.advanced_reports_enabled ? (
                          <Badge className="bg-violet-50 text-violet-700 ring-violet-200">
                            {t("adminPlans.featureAdvancedReportsShort")}
                          </Badge>
                        ) : null}
                      </div>
                    </td>
                    <td className={STICKY_ACTIONS_TD_CLASS}>
                      <RowActionsMenu label={t("common.moreActions")}>
                        <RowActionsMenu.Item
                          onSelect={() => {
                            setFormMode("edit");
                            setEditingPlan(plan);
                            setFormError(null);
                            setFormOpen(true);
                          }}
                        >
                          {t("common.edit")}
                        </RowActionsMenu.Item>
                        {plan.is_active ? (
                          <RowActionsMenu.Item
                            onSelect={() => {
                              setActionPlan(plan);
                              setActionMode("deactivate");
                              setActionError(null);
                            }}
                          >
                            {t("adminPlans.deactivateButton")}
                          </RowActionsMenu.Item>
                        ) : (
                          <RowActionsMenu.Item
                            onSelect={() => {
                              setActionPlan(plan);
                              setActionMode("activate");
                              setActionError(null);
                            }}
                          >
                            {t("adminPlans.activateButton")}
                          </RowActionsMenu.Item>
                        )}
                        {!plan.is_default && plan.is_active ? (
                          <RowActionsMenu.Item
                            onSelect={() => {
                              setActionPlan(plan);
                              setActionMode("make-default");
                              setActionError(null);
                            }}
                          >
                            {t("adminPlans.makeDefaultButton")}
                          </RowActionsMenu.Item>
                        ) : null}
                      </RowActionsMenu>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <PlanFormDialog
        open={formOpen}
        mode={formMode}
        plan={editingPlan}
        submitting={formSubmitting}
        error={formError}
        onClose={() => {
          if (!formSubmitting) {
            setFormOpen(false);
            setFormError(null);
          }
        }}
        onSubmitCreate={(body) => void handleCreate(body)}
        onSubmitEdit={(body) => void handleEdit(body)}
      />

      <PlanActionDialog
        open={actionPlan !== null && actionMode !== null}
        mode={actionMode ?? "activate"}
        planName={actionPlan?.name ?? ""}
        submitting={actionSubmitting}
        error={actionError}
        onClose={() => {
          if (!actionSubmitting) {
            setActionPlan(null);
            setActionMode(null);
            setActionError(null);
          }
        }}
        onConfirm={(reason) => void handleAction(reason)}
      />

      <VersionConflictDialog
        open={conflictSource !== null}
        reloading={conflictReloading}
        onReload={() => void handleReloadLatestPlan()}
        onCancel={() => setConflictSource(null)}
        titleKey="adminPlans.planVersionConflictTitle"
        messageKey="adminPlans.planVersionConflictMessage"
        reloadButtonKey="adminPlans.planVersionConflictReloadButton"
      />
    </div>
  );
}
