"use client";

import { useCallback, useEffect, useState } from "react";

import { CreateApiKeyForm } from "@/components/settings/CreateApiKeyForm";
import { ApiKeySecretDialog } from "@/components/settings/ApiKeySecretDialog";
import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { Badge } from "@/components/ui/Badge";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  RowActionsMenu,
  STICKY_ACTIONS_TD_CLASS,
  STICKY_ACTIONS_TH_CLASS,
} from "@/components/ui/RowActionsMenu";
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
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { getApiKeyPermissionLabel } from "@/lib/api-key-permissions";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type { ApiKey, ApiKeyCreated, ApiKeyStatus } from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

const STATUS_BADGE_CLASS: Record<ApiKeyStatus, string> = {
  active: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  revoked: "bg-slate-100 text-slate-500 ring-slate-200",
  expired: "bg-amber-50 text-amber-700 ring-amber-200",
};

function statusLabel(t: TranslateFn, status: ApiKeyStatus): string {
  return t(`apiKeys.status${status.charAt(0).toUpperCase()}${status.slice(1)}`);
}

function formatDateTime(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

export default function ApiKeysPage() {
  const { t, language } = useTranslation();
  const toast = useToast();

  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await apiFetch<ApiKey[]>(orgPath("api-keys"));
      setKeys(rows);
    } catch (e) {
      setKeys(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function handleCreated(created: ApiKeyCreated) {
    setRevealedKey(created.api_key);
    void load();
  }

  async function handleRotate(key: ApiKey) {
    if (!window.confirm(t("apiKeys.confirmRotate", { name: key.name }))) return;
    setBusyId(key.id);
    try {
      const rotated = await apiFetch<ApiKeyCreated>(orgPath(`api-keys/${key.id}/rotate`), { method: "POST" });
      toast.success(t("apiKeys.toastRotated"));
      setRevealedKey(rotated.api_key);
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("apiKeys.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  async function handleRevoke(key: ApiKey) {
    if (!window.confirm(t("apiKeys.confirmRevoke", { name: key.name }))) return;
    setBusyId(key.id);
    try {
      await apiFetch<ApiKey>(orgPath(`api-keys/${key.id}/revoke`), { method: "POST" });
      toast.success(t("apiKeys.toastRevoked"));
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("apiKeys.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <PageContainer>
      <PageHeader title={t("apiKeys.title")} subtitle={t("apiKeys.subtitle")} />
      <SettingsSubNav />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      <CreateApiKeyForm onCreated={handleCreated} />

      <section className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("apiKeys.colName")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("apiKeys.colPrefix")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("apiKeys.colPermissions")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("apiKeys.colStatus")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("apiKeys.colLastUsed")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("apiKeys.colExpires")}</th>
                <th className={STICKY_ACTIONS_TH_CLASS}>{t("common.moreActions")}</th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {loading ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={7}>
                    {t("apiKeys.loading")}
                  </td>
                </tr>
              ) : !keys || keys.length === 0 ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={7}>
                    {t("apiKeys.emptyState")}
                  </td>
                </tr>
              ) : (
                keys.map((key) => (
                  <tr key={key.id} className={TABLE_ROW_CLASS}>
                    <td className={TABLE_CELL_CLASS}>
                      <div className="font-medium text-slate-900">{key.name}</div>
                      {key.description ? <div className="text-xs text-slate-500">{key.description}</div> : null}
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <code className="font-mono text-xs text-slate-600">sk_{key.prefix}_…</code>
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <div className="flex flex-wrap gap-1">
                        {key.permissions.map((permission) => (
                          <Badge key={permission} className="bg-slate-100 text-slate-600 ring-slate-200">
                            {getApiKeyPermissionLabel(t, permission)}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      <Badge className={STATUS_BADGE_CLASS[key.status]}>{statusLabel(t, key.status)}</Badge>
                    </td>
                    <td className={TABLE_CELL_CLASS}>{formatDateTime(key.last_used_at, language)}</td>
                    <td className={TABLE_CELL_CLASS}>
                      {key.expires_at ? formatDateTime(key.expires_at, language) : t("apiKeys.neverExpires")}
                    </td>
                    <td className={STICKY_ACTIONS_TD_CLASS}>
                      <RowActionsMenu label={t("common.moreActions")}>
                        <RowActionsMenu.Item
                          disabled={busyId === key.id || key.status === "revoked"}
                          onSelect={() => void handleRotate(key)}
                        >
                          {t("apiKeys.rotateAction")}
                        </RowActionsMenu.Item>
                        <RowActionsMenu.Item
                          disabled={busyId === key.id || key.status === "revoked"}
                          onSelect={() => void handleRevoke(key)}
                        >
                          {t("apiKeys.revokeAction")}
                        </RowActionsMenu.Item>
                      </RowActionsMenu>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <ApiKeySecretDialog apiKey={revealedKey} onClose={() => setRevealedKey(null)} />
    </PageContainer>
  );
}
