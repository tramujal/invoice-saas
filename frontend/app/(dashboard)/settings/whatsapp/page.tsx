"use client";

import { useCallback, useEffect, useState } from "react";

import { WhatsAppHistoryTable } from "@/components/settings/WhatsAppHistoryTable";
import { WhatsAppIdentitiesTable } from "@/components/settings/WhatsAppIdentitiesTable";
import { WhatsAppLinkCard } from "@/components/settings/WhatsAppLinkCard";
import { WhatsAppQrDialog } from "@/components/settings/WhatsAppQrDialog";
import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/toast";
import { getUserEmail } from "@/lib/auth-storage";
import { ApiError, apiFetch, orgPath } from "@/lib/api";
import { formatApiError, getApiErrorCode } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import { hasPermission } from "@/lib/permissions";
import type {
  PaginatedMembers,
  WhatsAppCommandHistoryResponse,
  WhatsAppConnectionState,
  WhatsAppIdentityListResponse,
  WhatsAppIdentityResponse,
  WhatsAppQrResponse,
  WhatsAppStatusResponse,
} from "@/lib/types";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

const CONNECTION_BADGE_CLASS: Record<WhatsAppConnectionState, string> = {
  connected: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  connecting: "bg-amber-50 text-amber-700 ring-amber-200",
  qr_required: "bg-amber-50 text-amber-700 ring-amber-200",
  disconnected: "bg-slate-100 text-slate-500 ring-slate-200",
  session_expired: "bg-red-50 text-red-700 ring-red-200",
};

function connectionLabel(t: TranslateFn, state: WhatsAppConnectionState): string {
  return t(`whatsapp.connectionState.${state}`);
}

const SUPPORTED_READ_COMMAND_KEYS = [
  "whatsapp.example.help",
  "whatsapp.example.searchCustomer",
  "whatsapp.example.searchInvoice",
  "whatsapp.example.overdueInvoices",
  "whatsapp.example.monthlyRevenue",
  "whatsapp.example.sendInvoicePdf",
] as const;

const SUPPORTED_MUTATING_COMMAND_KEYS = [
  "whatsapp.example.createInvoice",
  "whatsapp.example.markPaid",
] as const;

export default function WhatsAppSettingsPage() {
  const { t } = useTranslation();
  const toast = useToast();

  const [userEmail, setUserEmail] = useState<string | null>(null);
  useEffect(() => {
    setUserEmail(getUserEmail());
  }, []);

  const [canManage, setCanManage] = useState(false);
  const [status, setStatus] = useState<WhatsAppStatusResponse | null>(null);
  const [ownIdentity, setOwnIdentity] = useState<WhatsAppIdentityResponse | null>(null);
  const [identities, setIdentities] = useState<WhatsAppIdentityResponse[] | null>(null);
  const [history, setHistory] = useState<WhatsAppCommandHistoryResponse["items"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [qr, setQr] = useState<WhatsAppQrResponse | null>(null);
  const [connectionBusy, setConnectionBusy] = useState<"qr" | "reconnect" | "disconnect" | "delete" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const membersResponse = await apiFetch<PaginatedMembers>(orgPath("members"));
      const self = membersResponse.items.find((m) => m.user_email === getUserEmail()) ?? null;
      const manage = hasPermission(self, "settings.manage");
      setCanManage(manage);

      const [statusResponse, meResponse] = await Promise.all([
        apiFetch<WhatsAppStatusResponse>(orgPath("whatsapp/status")),
        apiFetch<WhatsAppIdentityResponse | null>(orgPath("whatsapp/me")),
      ]);
      setStatus(statusResponse);
      setOwnIdentity(meResponse);

      if (manage) {
        const [identitiesResponse, historyResponse] = await Promise.all([
          apiFetch<WhatsAppIdentityListResponse>(orgPath("whatsapp/identities")),
          apiFetch<WhatsAppCommandHistoryResponse>(orgPath("whatsapp/history")),
        ]);
        setIdentities(identitiesResponse.items);
        setHistory(historyResponse.items);
      } else {
        setIdentities(null);
        setHistory(null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, userEmail]);

  function connectionErrorMessage(err: unknown): string {
    const code = getApiErrorCode(err);
    if (code === "whatsapp_not_configured") return t("whatsapp.errorNotConfigured");
    if (code === "whatsapp_bridge_unavailable") return t("whatsapp.errorBridgeUnavailable");
    return formatApiError(err, t("whatsapp.toastActionError"));
  }

  async function handleShowQr() {
    setConnectionBusy("qr");
    try {
      const result = await apiFetch<WhatsAppQrResponse>(orgPath("whatsapp/qr"), { method: "POST" });
      setQr(result);
    } catch (err) {
      toast.error(connectionErrorMessage(err));
    } finally {
      setConnectionBusy(null);
    }
  }

  async function handleReconnect() {
    setConnectionBusy("reconnect");
    try {
      await apiFetch(orgPath("whatsapp/reconnect"), { method: "POST" });
      toast.success(t("whatsapp.toastReconnecting"));
      await load();
    } catch (err) {
      toast.error(connectionErrorMessage(err));
    } finally {
      setConnectionBusy(null);
    }
  }

  async function handleDisconnect() {
    if (!window.confirm(t("whatsapp.confirmDisconnect"))) return;
    setConnectionBusy("disconnect");
    try {
      await apiFetch(orgPath("whatsapp/disconnect"), { method: "POST" });
      toast.success(t("whatsapp.toastDisconnected"));
      await load();
    } catch (err) {
      toast.error(connectionErrorMessage(err));
    } finally {
      setConnectionBusy(null);
    }
  }

  async function handleDeleteSession() {
    if (!window.confirm(t("whatsapp.confirmDeleteSession"))) return;
    setConnectionBusy("delete");
    try {
      await apiFetch(orgPath("whatsapp/session/delete"), { method: "POST" });
      toast.success(t("whatsapp.toastSessionDeleted"));
      await load();
    } catch (err) {
      toast.error(connectionErrorMessage(err));
    } finally {
      setConnectionBusy(null);
    }
  }

  const canUseWhatsapp = Boolean(status?.transport_enabled && status?.plan_allows_whatsapp);

  return (
    <PageContainer>
      <PageHeader
        title={t("whatsapp.title")}
        subtitle={t("whatsapp.subtitle")}
        actions={<Badge className="bg-violet-50 text-violet-700 ring-violet-200">{t("whatsapp.experimentalBadge")}</Badge>}
      />
      <SettingsSubNav />

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="alert">
        {t("whatsapp.unofficialWarning")}
      </div>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      {loading && !status ? (
        // Only the very first load shows this skeleton in place of the
        // page. A background refresh (e.g. after linking/revoking a
        // number) leaves the already-rendered tree mounted instead of
        // swapping it for this placeholder -- swapping would unmount
        // WhatsAppLinkCard along with it, wiping the one-time
        // verification code it just displayed before the user could
        // read it (see WhatsAppLinkCard's own pendingLink state).
        <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
          {t("whatsapp.loading")}
        </div>
      ) : status ? (
        <>
          {!status.transport_enabled ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              {t("whatsapp.transportDisabled")}
            </div>
          ) : !status.transport_configured ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              {t("whatsapp.transportUnconfigured")}
            </div>
          ) : null}

          {status.transport_enabled && !status.plan_allows_whatsapp ? (
            <div className="rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900">
              {t("whatsapp.planRestricted")}
            </div>
          ) : null}

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                  {t("whatsapp.connectionTitle")}
                </h2>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Badge className={CONNECTION_BADGE_CLASS[status.connection.state]}>
                    {connectionLabel(t, status.connection.state)}
                  </Badge>
                  {status.connection.connected_phone_number ? (
                    <span className="font-mono text-xs text-slate-600">
                      {status.connection.connected_phone_number}
                    </span>
                  ) : null}
                </div>
              </div>

              {canManage ? (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => void handleShowQr()}
                    loading={connectionBusy === "qr"}
                    disabled={connectionBusy !== null}
                  >
                    {t("whatsapp.showQrButton")}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => void handleReconnect()}
                    loading={connectionBusy === "reconnect"}
                    disabled={connectionBusy !== null}
                  >
                    {t("whatsapp.reconnectButton")}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => void handleDisconnect()}
                    loading={connectionBusy === "disconnect"}
                    disabled={connectionBusy !== null}
                  >
                    {t("whatsapp.disconnectButton")}
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    size="sm"
                    onClick={() => void handleDeleteSession()}
                    loading={connectionBusy === "delete"}
                    disabled={connectionBusy !== null}
                  >
                    {t("whatsapp.deleteSessionButton")}
                  </Button>
                </div>
              ) : null}
            </div>

            <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-slate-200 px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {t("whatsapp.quotaUsersLabel")}
                </dt>
                <dd className="mt-1 text-sm text-slate-900">
                  {status.whatsapp_users_quota.used}
                  {status.whatsapp_users_quota.unlimited ? "" : ` / ${status.whatsapp_users_quota.limit}`}
                </dd>
              </div>
              <div className="rounded-xl border border-slate-200 px-4 py-3">
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {t("whatsapp.quotaActionsLabel")}
                </dt>
                <dd className="mt-1 text-sm text-slate-900">
                  {status.whatsapp_actions_quota.used}
                  {status.whatsapp_actions_quota.unlimited ? "" : ` / ${status.whatsapp_actions_quota.limit}`}
                </dd>
              </div>
            </dl>
          </section>

          <WhatsAppLinkCard identity={ownIdentity} canUseWhatsapp={canUseWhatsapp} onChanged={() => void load()} />

          {canManage ? (
            <>
              <WhatsAppIdentitiesTable identities={identities} loading={loading} onChanged={() => void load()} />
              <WhatsAppHistoryTable items={history} loading={loading} />
            </>
          ) : null}

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("whatsapp.commandsTitle")}
            </h2>
            <p className="mt-1 text-sm text-slate-500">{t("whatsapp.commandsSubtitle")}</p>
            <ul className="mt-3 space-y-1.5 text-sm text-slate-700">
              {SUPPORTED_READ_COMMAND_KEYS.map((key) => (
                <li key={key} className="rounded-lg bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
                  {t(key)}
                </li>
              ))}
            </ul>
            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {t("whatsapp.mutatingCommandsTitle")}
            </h3>
            <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
              {SUPPORTED_MUTATING_COMMAND_KEYS.map((key) => (
                <li key={key} className="rounded-lg bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
                  {t(key)}
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("whatsapp.troubleshootingTitle")}
            </h2>
            <p className="mt-2 whitespace-pre-line text-sm text-slate-600">{t("whatsapp.troubleshootingBody")}</p>
          </section>
        </>
      ) : null}

      <WhatsAppQrDialog qr={qr} onClose={() => setQr(null)} />
    </PageContainer>
  );
}
