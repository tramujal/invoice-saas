"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { type SimpleConfirmMode, SimpleConfirmDialog } from "@/components/admin/SimpleConfirmDialog";
import { type UserActionMode, UserActionDialog } from "@/components/admin/UserActionDialog";
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
import { getUserEmail } from "@/lib/auth-storage";
import { ApiError, apiFetch } from "@/lib/api";
import { getApiErrorCode } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { PlatformUserActionResponse, PlatformUserDetail } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

function formatApproxDate(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" });
}

function mutationErrorMessage(t: (key: string) => string, err: unknown): string {
  const code = getApiErrorCode(err);
  if (code === "user_already_disabled") return t("admin.errorUserAlreadyDisabled");
  if (code === "user_already_active") return t("admin.errorUserAlreadyActive");
  if (code === "already_verified") return t("admin.errorAlreadyVerified");
  if (code === "cannot_disable_self") return t("admin.errorCannotDisableSelf");
  if (code === "cannot_disable_last_super_admin") return t("admin.errorCannotDisableLastSuperAdmin");
  if (code === "cannot_modify_own_platform_role") return t("admin.errorCannotModifyOwnRole");
  if (code === "cannot_revoke_last_super_admin") return t("admin.errorCannotRevokeLastSuperAdmin");
  if (code === "platform_role_unchanged") return t("admin.errorPlatformRoleUnchanged");
  return err instanceof ApiError ? err.message : t("admin.mutationErrorGeneric");
}

export default function PlatformUserDetailPage() {
  const params = useParams<{ id: string }>();
  const { t, language } = useTranslation();
  const toast = useToast();
  const [data, setData] = useState<PlatformUserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userActionMode, setUserActionMode] = useState<UserActionMode | null>(null);
  const [simpleActionMode, setSimpleActionMode] = useState<SimpleConfirmMode | null>(null);
  const [mutating, setMutating] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const currentUserEmail = getUserEmail();
  const isSelf = Boolean(data && currentUserEmail && data.email === currentUserEmail);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const json = await apiFetch<PlatformUserDetail>(`/admin/users/${params.id}`, {
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

  async function handleUserActionConfirm(reason: string) {
    if (!userActionMode) return;
    setMutating(true);
    setMutationError(null);
    try {
      const endpoint =
        userActionMode === "disable"
          ? "disable"
          : userActionMode === "enable"
            ? "enable"
            : "platform-role";
      const body =
        userActionMode === "grant-role"
          ? { role: "super_admin", reason }
          : userActionMode === "revoke-role"
            ? { role: null, reason }
            : { reason };
      // The mutation response IS the refreshed detail -- never an
      // optimistic local update, and never a second GET just to see our
      // own result.
      const updated = await apiFetch<PlatformUserDetail>(`/admin/users/${params.id}/${endpoint}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setData(updated);
      setUserActionMode(null);
      const toastKey: Record<UserActionMode, string> = {
        disable: "admin.disableSuccessToast",
        enable: "admin.enableSuccessToast",
        "grant-role": "admin.grantRoleSuccessToast",
        "revoke-role": "admin.revokeRoleSuccessToast",
      };
      toast.success(t(toastKey[userActionMode]));
    } catch (e) {
      setMutationError(mutationErrorMessage(t, e));
    } finally {
      setMutating(false);
    }
  }

  async function handleSimpleActionConfirm() {
    if (!simpleActionMode) return;
    setMutating(true);
    setMutationError(null);
    try {
      if (simpleActionMode === "verify-email") {
        const updated = await apiFetch<PlatformUserDetail>(`/admin/users/${params.id}/verify-email`, {
          method: "POST",
        });
        setData(updated);
        toast.success(t("admin.verifyEmailSuccessToast"));
      } else {
        const result = await apiFetch<PlatformUserActionResponse>(
          `/admin/users/${params.id}/send-password-reset`,
          { method: "POST" }
        );
        toast.success(result.message);
      }
      setSimpleActionMode(null);
    } catch (e) {
      setMutationError(mutationErrorMessage(t, e));
    } finally {
      setMutating(false);
    }
  }

  function openUserAction(mode: UserActionMode) {
    setMutationError(null);
    setUserActionMode(mode);
  }

  function openSimpleAction(mode: SimpleConfirmMode) {
    setMutationError(null);
    setSimpleActionMode(mode);
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-3xl">
        <Link href="/admin/users" className="text-sm font-medium text-slate-600 hover:text-slate-900">
          {t("admin.backToUsers")}
        </Link>
        <div className="mt-4">
          <EmptyState title={t("admin.userNotFoundTitle")} description={t("admin.userNotFoundDescription")} />
        </div>
      </div>
    );
  }

  const hasPlatformRole = Boolean(data?.platform_role);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link href="/admin/users" className="text-sm font-medium text-slate-600 hover:text-slate-900">
        {t("admin.backToUsers")}
      </Link>

      <PageHeader
        title={loading && !data ? t("admin.loadingUsers") : (data?.email ?? "")}
        actions={
          data && !isSelf ? (
            <div className="flex flex-wrap items-center gap-2">
              {data.status === "active" ? (
                <Button type="button" variant="danger" size="sm" onClick={() => openUserAction("disable")}>
                  {t("admin.disableButton")}
                </Button>
              ) : (
                <Button type="button" size="sm" onClick={() => openUserAction("enable")}>
                  {t("admin.enableButton")}
                </Button>
              )}
              {hasPlatformRole ? (
                <Button type="button" variant="secondary" size="sm" onClick={() => openUserAction("revoke-role")}>
                  {t("admin.revokeRoleButton")}
                </Button>
              ) : (
                <Button type="button" variant="secondary" size="sm" onClick={() => openUserAction("grant-role")}>
                  {t("admin.grantRoleButton")}
                </Button>
              )}
            </div>
          ) : undefined
        }
      />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <dl className="divide-y divide-slate-100">
          <div className="flex items-center justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700">{t("admin.colStatus")}</dt>
            <dd>
              {loading ? (
                <span className="inline-flex h-6 w-16 animate-pulse rounded-full bg-slate-100" aria-hidden />
              ) : (
                <Badge
                  className={
                    data?.status === "active"
                      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                      : "bg-red-50 text-red-700 ring-red-200"
                  }
                >
                  {data?.status === "active" ? t("admin.statusActive") : t("admin.statusDisabled")}
                </Badge>
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700">{t("admin.colVerified")}</dt>
            <dd className="flex items-center gap-2">
              {loading ? (
                <span className="inline-flex h-6 w-16 animate-pulse rounded-full bg-slate-100" aria-hidden />
              ) : (
                <>
                  <Badge
                    className={
                      data?.email_verified
                        ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                        : "bg-slate-100 text-slate-600 ring-slate-200"
                    }
                  >
                    {data?.email_verified ? t("common.yes") : t("common.no")}
                  </Badge>
                  {!data?.email_verified ? (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => openSimpleAction("verify-email")}
                    >
                      {t("admin.verifyEmailButton")}
                    </Button>
                  ) : null}
                </>
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700">{t("admin.colPlatformRole")}</dt>
            <dd className="text-sm text-slate-900">
              {loading ? (
                <span className="inline-flex h-4 w-20 animate-pulse rounded bg-slate-100" aria-hidden />
              ) : (
                (data?.platform_role ?? "—")
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700" title={t("admin.createdApprox")}>
              {t("admin.colCreated")}
            </dt>
            <dd className="text-sm text-slate-900">
              {loading ? (
                <span className="inline-flex h-4 w-24 animate-pulse rounded bg-slate-100" aria-hidden />
              ) : (
                formatApproxDate(data?.created_at ?? null, language)
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-4">
            <dt className="text-sm font-medium text-slate-700">{t("admin.sendResetLabel")}</dt>
            <dd>
              <Button type="button" variant="secondary" size="sm" onClick={() => openSimpleAction("send-password-reset")}>
                {t("admin.sendResetButton")}
              </Button>
            </dd>
          </div>
        </dl>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-900">{t("admin.userOrganizationsTitle")}</h2>
        <div className={`mt-3 ${TABLE_WRAPPER_CLASS}`}>
          <div className="overflow-x-auto">
            <table className={TABLE_CLASS}>
              <thead className={TABLE_HEAD_CLASS}>
                <tr>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("common.name")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colRole")}</th>
                  <th className={TABLE_HEAD_CELL_CLASS}>{t("admin.colStatus")}</th>
                </tr>
              </thead>
              <tbody className={TABLE_BODY_CLASS}>
                {loading ? (
                  <tr>
                    <td colSpan={3} className={`text-center text-slate-500 ${TABLE_CELL_CLASS}`}>
                      {t("admin.loadingUsers")}
                    </td>
                  </tr>
                ) : data && data.organizations.length === 0 ? (
                  <tr>
                    <td colSpan={3} className={TABLE_CELL_CLASS}>
                      <EmptyState
                        title={t("admin.userNoOrganizationsTitle")}
                        description={t("admin.userNoOrganizationsDescription")}
                      />
                    </td>
                  </tr>
                ) : (
                  data?.organizations.map((org) => (
                    <tr key={org.organization_id} className={TABLE_ROW_CLASS}>
                      <td className={TABLE_CELL_CLASS}>
                        <Link
                          href={`/admin/organizations/${org.organization_id}`}
                          className="font-medium text-slate-900 hover:underline"
                        >
                          {org.organization_name}
                        </Link>
                      </td>
                      <td className={TABLE_CELL_CLASS}>{org.role}</td>
                      <td className={TABLE_CELL_CLASS}>
                        <Badge
                          className={
                            org.status === "active"
                              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                              : "bg-slate-100 text-slate-600 ring-slate-200"
                          }
                        >
                          {org.status}
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

      {data && userActionMode ? (
        <UserActionDialog
          open
          mode={userActionMode}
          userEmail={data.email}
          submitting={mutating}
          error={mutationError}
          onClose={() => {
            if (mutating) return;
            setUserActionMode(null);
            setMutationError(null);
          }}
          onConfirm={(reason) => void handleUserActionConfirm(reason)}
        />
      ) : null}

      {simpleActionMode ? (
        <SimpleConfirmDialog
          open
          mode={simpleActionMode}
          submitting={mutating}
          error={mutationError}
          onClose={() => {
            if (mutating) return;
            setSimpleActionMode(null);
            setMutationError(null);
          }}
          onConfirm={() => void handleSimpleActionConfirm()}
        />
      ) : null}
    </div>
  );
}
