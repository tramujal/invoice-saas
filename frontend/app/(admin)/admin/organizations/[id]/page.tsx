"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { OrganizationPlanChangeDialog } from "@/components/admin/OrganizationPlanChangeDialog";
import { SuspendReactivateDialog } from "@/components/admin/SuspendReactivateDialog";
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
import { useToast } from "@/components/ui/toast";
import { ApiError, apiFetch } from "@/lib/api";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { formatUsage } from "@/lib/plan-limits";
import type { Plan, PlansListResponse, PlatformOrganizationDetail, UsageResourceSnapshot } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

function formatApproxDate(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

export default function PlatformOrganizationDetailPage() {
  const params = useParams<{ id: string }>();
  const { t, language } = useTranslation();
  const toast = useToast();
  const [data, setData] = useState<PlatformOrganizationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialogMode, setDialogMode] = useState<"suspend" | "reactivate" | null>(null);
  const [mutating, setMutating] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [planDialogOpen, setPlanDialogOpen] = useState(false);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [planMutating, setPlanMutating] = useState(false);
  const [planMutationError, setPlanMutationError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const json = await apiFetch<PlatformOrganizationDetail>(`/admin/organizations/${params.id}`, {
        signal: controller.signal,
      });
      setData(json);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      if (e instanceof ApiError && e.status === 404) {
        setNotFound(true);
      } else {
        setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
      }
    } finally {
      if (abortRef.current === controller) setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  async function handleConfirmMutation(reason: string) {
    if (!dialogMode) return;
    setMutating(true);
    setMutationError(null);
    try {
      // The mutation response IS the refreshed detail -- never an
      // optimistic local update, and never a second GET just to see our
      // own result.
      const updated = await apiFetch<PlatformOrganizationDetail>(
        `/admin/organizations/${params.id}/${dialogMode}`,
        { method: "POST", body: JSON.stringify({ reason }) }
      );
      setData(updated);
      setDialogMode(null);
      toast.success(
        dialogMode === "suspend" ? t("admin.suspendSuccessToast") : t("admin.reactivateSuccessToast")
      );
    } catch (e) {
      setMutationError(e instanceof ApiError ? e.message : t("admin.mutationErrorGeneric"));
    } finally {
      setMutating(false);
    }
  }

  async function openPlanDialog() {
    setPlanMutationError(null);
    setPlanDialogOpen(true);
    setPlansLoading(true);
    try {
      const json = await apiFetch<PlansListResponse>("/admin/plans");
      setPlans(json.items.filter((plan) => plan.is_active));
    } catch {
      setPlans([]);
    } finally {
      setPlansLoading(false);
    }
  }

  async function handleConfirmPlanChange(planId: string, reason: string) {
    setPlanMutating(true);
    setPlanMutationError(null);
    try {
      // The mutation response IS the refreshed detail -- never an
      // optimistic local update, matching handleConfirmMutation above.
      const updated = await apiFetch<PlatformOrganizationDetail>(`/admin/organizations/${params.id}/plan`, {
        method: "PATCH",
        body: JSON.stringify({ plan_id: planId, reason }),
      });
      setData(updated);
      setPlanDialogOpen(false);
      toast.success(t("adminPlans.orgPlanChangedToast"));
    } catch (e) {
      setPlanMutationError(e instanceof ApiError ? e.message : t("admin.mutationErrorGeneric"));
    } finally {
      setPlanMutating(false);
    }
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-3xl">
        <Link href="/admin/organizations" className="text-sm font-medium text-slate-600 hover:text-slate-900">
          {t("admin.backToOrganizations")}
        </Link>
        <div className="mt-4">
          <EmptyState title={t("admin.orgNotFoundTitle")} description={t("admin.orgNotFoundDescription")} />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link href="/admin/organizations" className="text-sm font-medium text-slate-600 hover:text-slate-900">
        {t("admin.backToOrganizations")}
      </Link>

      <PageHeader
        title={loading && !data ? t("admin.loadingOrganizations") : (data?.name ?? "")}
        subtitle={data?.business_name ?? undefined}
        actions={
          data ? (
            data.status === "active" ? (
              <Button
                type="button"
                variant="danger"
                size="sm"
                onClick={() => {
                  setMutationError(null);
                  setDialogMode("suspend");
                }}
              >
                {t("admin.suspendButton")}
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  setMutationError(null);
                  setDialogMode("reactivate");
                }}
              >
                {t("admin.reactivateButton")}
              </Button>
            )
          ) : undefined
        }
      />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label={t("admin.colMembers")} value={data?.members_count} loading={loading} />
        <Stat label={t("admin.colInvoices")} value={data?.invoices_count} loading={loading} />
        <Stat label={t("admin.colQuotes")} value={data?.quotes_count} loading={loading} />
        <Stat label={t("admin.colCustomers")} value={data?.customers_count} loading={loading} />
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <dl className="divide-y divide-slate-100">
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm font-medium text-slate-700">{t("admin.colStatus")}</dt>
            <dd>
              {loading ? (
                <span className="inline-flex h-6 w-20 animate-pulse rounded-full bg-slate-100" aria-hidden />
              ) : (
                <Badge
                  className={
                    data?.status === "active"
                      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                      : "bg-red-50 text-red-700 ring-red-200"
                  }
                >
                  {data?.status === "active" ? t("admin.statusActive") : t("admin.statusSuspended")}
                </Badge>
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm font-medium text-slate-700">{t("adminPlans.currentPlanLabel")}</dt>
            <dd className="flex items-center gap-3">
              {loading ? (
                <span className="inline-flex h-4 w-24 animate-pulse rounded bg-slate-100" aria-hidden />
              ) : (
                <>
                  <span className="text-sm text-slate-900">{data?.plan_name}</span>
                  <Button type="button" variant="secondary" size="sm" onClick={() => void openPlanDialog()}>
                    {t("adminPlans.changePlanButton")}
                  </Button>
                </>
              )}
            </dd>
          </div>
          <InfoRow label={t("admin.colOwner")} value={data?.owner_email ?? "—"} loading={loading} />
          <InfoRow label={t("admin.orgLanguageLabel")} value={data?.language} loading={loading} />
          <InfoRow label={t("admin.orgCurrencyLabel")} value={data?.currency_code} loading={loading} />
          <InfoRow label={t("admin.orgTimezoneLabel")} value={data?.timezone} loading={loading} />
          <InfoRow
            label={t("admin.colCreated")}
            value={formatApproxDate(data?.created_at ?? null, language)}
            loading={loading}
            hint={t("admin.createdApprox")}
          />
          <InfoRow
            label={t("admin.colLastActivity")}
            value={formatApproxDate(data?.last_activity_at ?? null, language)}
            loading={loading}
          />
        </dl>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">
          {t("adminPlans.usageSectionTitle")}
        </h2>
        <dl className="divide-y divide-slate-100">
          {(
            [
              ["adminPlans.usageRowUsers", data?.usage.users],
              ["adminPlans.usageRowCustomers", data?.usage.customers],
              ["adminPlans.usageRowProducts", data?.usage.products],
              ["adminPlans.usageRowInvoices", data?.usage.invoices],
              ["adminPlans.usageRowQuotes", data?.usage.quotes],
              ["adminPlans.usageRowAiActions", data?.usage.ai_actions],
            ] as [string, UsageResourceSnapshot | undefined][]
          ).map(([labelKey, resource]) => (
            <div key={labelKey} className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-sm font-medium text-slate-700">{t(labelKey)}</dt>
              <dd className="text-sm text-slate-900">
                {loading || !resource ? (
                  <span className="inline-flex h-4 w-16 animate-pulse rounded bg-slate-100" aria-hidden />
                ) : (
                  formatUsage(resource.used, resource.limit, t)
                )}
              </dd>
            </div>
          ))}
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm font-medium text-slate-700">{t("adminPlans.usageRowStorage")}</dt>
            <dd className="text-sm text-slate-900">
              {loading || !data ? (
                <span className="inline-flex h-4 w-16 animate-pulse rounded bg-slate-100" aria-hidden />
              ) : data.usage.storage.unlimited ? (
                t("planLimits.unlimited")
              ) : data.usage.storage.limit === 0 ? (
                t("planLimits.unavailable")
              ) : (
                t("planAndLimits.storageUsageValue", {
                  used: data.usage.storage.used,
                  mb: data.usage.storage.limit ?? 0,
                })
              )}
            </dd>
          </div>
        </dl>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-900">{t("admin.orgMembersTitle")}</h2>
        <div className={`mt-3 ${TABLE_WRAPPER_CLASS}`}>
          <div className="overflow-x-auto">
            <table className={TABLE_CLASS}>
              <thead className={TABLE_HEAD_CLASS}>
                <tr>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("common.email")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colRole")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colStatus")}</th>
                </tr>
              </thead>
              <tbody className={TABLE_BODY_CLASS}>
                {loading ? (
                  <tr>
                    <td colSpan={3} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                      {t("admin.loadingOrganizations")}
                    </td>
                  </tr>
                ) : (
                  data?.members.map((member) => (
                    <tr key={member.user_id} className={TABLE_ROW_CLASS}>
                      <td className={TABLE_CELL_CLASS}>{member.email}</td>
                      <td className={TABLE_CELL_CLASS}>{member.role}</td>
                      <td className={TABLE_CELL_CLASS}>
                        <Badge
                          className={
                            member.status === "active"
                              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                              : "bg-slate-100 text-slate-600 ring-slate-200"
                          }
                        >
                          {member.status}
                        </Badge>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-900">{t("admin.orgRecentActivityTitle")}</h2>
        <div className={`mt-3 ${TABLE_WRAPPER_CLASS}`}>
          <div className="overflow-x-auto">
            <table className={TABLE_CLASS}>
              <thead className={TABLE_HEAD_CLASS}>
                <tr>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colType")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colNumber")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colStatus")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colTotal")}</th>
                </tr>
              </thead>
              <tbody className={TABLE_BODY_CLASS}>
                {loading ? (
                  <tr>
                    <td colSpan={4} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                      {t("admin.loadingOrganizations")}
                    </td>
                  </tr>
                ) : data && data.recent_documents.length === 0 ? (
                  <tr>
                    <td colSpan={4} className={TABLE_CELL_CLASS}>
                      <EmptyState
                        title={t("admin.emptyActivityTitle")}
                        description={t("admin.emptyActivityDescription")}
                      />
                    </td>
                  </tr>
                ) : (
                  data?.recent_documents.map((doc, index) => (
                    <tr key={`${doc.type}-${doc.number}-${index}`} className={TABLE_ROW_CLASS}>
                      <td className={`capitalize ${TABLE_CELL_CLASS}`}>
                        {doc.type === "invoice" ? t("nav.invoices") : t("nav.quotes")}
                      </td>
                      <td className={TABLE_CELL_CLASS}>{doc.number}</td>
                      <td className={`capitalize ${TABLE_CELL_CLASS}`}>{doc.status}</td>
                      <td className={TABLE_CELL_CLASS}>
                        {doc.currency_code} {doc.total}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {data && dialogMode ? (
        <SuspendReactivateDialog
          open
          mode={dialogMode}
          organizationName={data.name}
          submitting={mutating}
          error={mutationError}
          onClose={() => {
            if (mutating) return;
            setDialogMode(null);
            setMutationError(null);
          }}
          onConfirm={(reason) => void handleConfirmMutation(reason)}
        />
      ) : null}

      {data ? (
        <OrganizationPlanChangeDialog
          open={planDialogOpen}
          organizationName={data.name}
          currentPlanId={data.plan_id}
          plans={plans}
          loadingPlans={plansLoading}
          submitting={planMutating}
          error={planMutationError}
          onClose={() => {
            if (planMutating) return;
            setPlanDialogOpen(false);
            setPlanMutationError(null);
          }}
          onConfirm={(planId, reason) => void handleConfirmPlanChange(planId, reason)}
        />
      ) : null}
    </div>
  );
}

function InfoRow({
  label,
  value,
  loading,
  hint,
}: {
  label: string;
  value: string | undefined;
  loading: boolean;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3">
      <dt className="text-sm font-medium text-slate-700" title={hint}>
        {label}
      </dt>
      <dd className="text-sm text-slate-900">
        {loading ? <span className="inline-flex h-4 w-24 animate-pulse rounded bg-slate-100" aria-hidden /> : value}
      </dd>
    </div>
  );
}

function Stat({ label, value, loading }: { label: string; value: number | undefined; loading: boolean }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 text-center shadow-sm">
      {loading ? (
        <div className="mx-auto h-7 w-10 animate-pulse rounded bg-slate-100" aria-hidden />
      ) : (
        <p className="text-xl font-semibold text-slate-900">{value ?? "—"}</p>
      )}
      <p className="mt-1 text-xs text-slate-500">{label}</p>
    </div>
  );
}
