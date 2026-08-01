"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { CreateWebhookEndpointForm } from "@/components/settings/CreateWebhookEndpointForm";
import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { WebhookSecretDialog } from "@/components/settings/WebhookSecretDialog";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
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
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { TranslateFn } from "@/lib/i18n/useTranslation";
import type {
  PaginatedWebhookDeliveries,
  WebhookDelivery,
  WebhookDeliveryDetail,
  WebhookDeliveryStatus,
  WebhookEndpoint,
  WebhookEndpointCreated,
} from "@/lib/types";
import { getWebhookEventLabel } from "@/lib/webhook-events";

const GENERIC_LOAD_ERROR = "__generic_load_error__";

const ENDPOINT_STATUS_BADGE_CLASS: Record<"enabled" | "disabled" | "archived", string> = {
  enabled: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  disabled: "bg-amber-50 text-amber-700 ring-amber-200",
  archived: "bg-slate-100 text-slate-500 ring-slate-200",
};

const DELIVERY_STATUS_BADGE_CLASS: Record<WebhookDeliveryStatus, string> = {
  pending: "bg-sky-50 text-sky-700 ring-sky-200",
  succeeded: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-red-200",
};

function endpointStatusKey(endpoint: WebhookEndpoint): "enabled" | "disabled" | "archived" {
  if (!endpoint.active) return "archived";
  return endpoint.enabled ? "enabled" : "disabled";
}

function formatDateTime(value: string | null, locale: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

function summarizeEvents(t: TranslateFn, subscribedEvents: string[]): string {
  if (subscribedEvents.includes("*")) return t("webhooks.allEventsLabel");
  if (subscribedEvents.length === 1) return getWebhookEventLabel(t, subscribedEvents[0]);
  return t("webhooks.eventCount", { count: String(subscribedEvents.length) });
}

function triggerLabel(t: TranslateFn, trigger: WebhookDelivery["trigger"]): string {
  if (trigger === "manual_resend") return t("webhooks.triggerManual");
  if (trigger === "automatic_retry") return t("webhooks.triggerAutomaticRetry");
  return t("webhooks.triggerAutomatic");
}

export default function WebhooksPage() {
  const { t, language } = useTranslation();
  const toast = useToast();

  const [endpoints, setEndpoints] = useState<WebhookEndpoint[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);
  const [deliveriesEndpointId, setDeliveriesEndpointId] = useState<string | null>(null);
  const [deliveryDetailId, setDeliveryDetailId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await apiFetch<WebhookEndpoint[]>(orgPath("webhooks"));
      setEndpoints(rows);
    } catch (e) {
      setEndpoints(null);
      setError(e instanceof ApiError ? e.message : GENERIC_LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function handleCreated(created: WebhookEndpointCreated) {
    setRevealedSecret(created.secret);
    void load();
  }

  async function handleRotate(endpoint: WebhookEndpoint) {
    if (!window.confirm(t("webhooks.confirmRotate", { url: endpoint.url }))) return;
    setBusyId(endpoint.id);
    try {
      const rotated = await apiFetch<WebhookEndpointCreated>(orgPath(`webhooks/${endpoint.id}/rotate-secret`), {
        method: "POST",
      });
      toast.success(t("webhooks.toastRotated"));
      setRevealedSecret(rotated.secret);
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("webhooks.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggleEnabled(endpoint: WebhookEndpoint) {
    setBusyId(endpoint.id);
    try {
      const action = endpoint.enabled ? "disable" : "enable";
      await apiFetch<WebhookEndpoint>(orgPath(`webhooks/${endpoint.id}/${action}`), { method: "POST" });
      toast.success(endpoint.enabled ? t("webhooks.toastDisabled") : t("webhooks.toastEnabled"));
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("webhooks.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  async function handleArchive(endpoint: WebhookEndpoint) {
    if (!window.confirm(t("webhooks.confirmArchive", { url: endpoint.url }))) return;
    setBusyId(endpoint.id);
    try {
      await apiFetch<WebhookEndpoint>(orgPath(`webhooks/${endpoint.id}`), { method: "DELETE" });
      toast.success(t("webhooks.toastArchived"));
      if (deliveriesEndpointId === endpoint.id) setDeliveriesEndpointId(null);
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("webhooks.toastActionError")));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title={t("webhooks.title")} subtitle={t("webhooks.subtitle")} />
      <SettingsSubNav />

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {error === GENERIC_LOAD_ERROR ? t("admin.loadError") : error}
        </div>
      ) : null}

      <CreateWebhookEndpointForm onCreated={handleCreated} />

      <section className={TABLE_WRAPPER_CLASS}>
        <div className="overflow-x-auto">
          <table className={TABLE_CLASS}>
            <thead className={TABLE_HEAD_CLASS}>
              <tr>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("webhooks.colUrl")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("webhooks.colEvents")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("webhooks.colStatus")}</th>
                <th className={TABLE_HEAD_CELL_CLASS}>{t("webhooks.colLastRotated")}</th>
                <th className={STICKY_ACTIONS_TH_CLASS}>{t("common.moreActions")}</th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY_CLASS}>
              {loading ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={5}>
                    {t("webhooks.loading")}
                  </td>
                </tr>
              ) : !endpoints || endpoints.length === 0 ? (
                <tr>
                  <td className={TABLE_CELL_CLASS} colSpan={5}>
                    <EmptyState
                      title={t("webhooks.emptyTitle")}
                      description={t("webhooks.emptyDescription")}
                      className="border-none bg-transparent px-0 py-6"
                    />
                  </td>
                </tr>
              ) : (
                endpoints.map((endpoint) => {
                  const statusKey = endpointStatusKey(endpoint);
                  return (
                    <>
                      <tr key={endpoint.id} className={TABLE_ROW_CLASS}>
                        <td className={TABLE_CELL_CLASS}>
                          <div className="max-w-xs truncate font-mono text-xs text-slate-800" title={endpoint.url}>
                            {endpoint.url}
                          </div>
                          {endpoint.description ? (
                            <div className="text-xs text-slate-500">{endpoint.description}</div>
                          ) : null}
                        </td>
                        <td className={TABLE_CELL_CLASS}>{summarizeEvents(t, endpoint.subscribed_events)}</td>
                        <td className={TABLE_CELL_CLASS}>
                          <Badge className={ENDPOINT_STATUS_BADGE_CLASS[statusKey]}>
                            {t(`webhooks.status${statusKey.charAt(0).toUpperCase()}${statusKey.slice(1)}`)}
                          </Badge>
                        </td>
                        <td className={TABLE_CELL_CLASS}>{formatDateTime(endpoint.last_rotated_at, language)}</td>
                        <td className={STICKY_ACTIONS_TD_CLASS}>
                          <RowActionsMenu label={t("common.moreActions")}>
                            <RowActionsMenu.Item
                              onSelect={() =>
                                setDeliveriesEndpointId(deliveriesEndpointId === endpoint.id ? null : endpoint.id)
                              }
                            >
                              {t("webhooks.viewDeliveriesAction")}
                            </RowActionsMenu.Item>
                            <RowActionsMenu.Item
                              disabled={busyId === endpoint.id || !endpoint.active}
                              onSelect={() => void handleToggleEnabled(endpoint)}
                            >
                              {endpoint.enabled ? t("webhooks.disableAction") : t("webhooks.enableAction")}
                            </RowActionsMenu.Item>
                            <RowActionsMenu.Item
                              disabled={busyId === endpoint.id || !endpoint.active}
                              onSelect={() => void handleRotate(endpoint)}
                            >
                              {t("webhooks.rotateAction")}
                            </RowActionsMenu.Item>
                            <RowActionsMenu.Item
                              disabled={busyId === endpoint.id || !endpoint.active}
                              onSelect={() => void handleArchive(endpoint)}
                            >
                              {t("webhooks.archiveAction")}
                            </RowActionsMenu.Item>
                          </RowActionsMenu>
                        </td>
                      </tr>
                      {deliveriesEndpointId === endpoint.id ? (
                        <tr key={`${endpoint.id}-deliveries`}>
                          <td colSpan={5} className="bg-slate-50 px-4 py-4 sm:px-6">
                            <DeliveriesPanel
                              endpointId={endpoint.id}
                              onViewDetail={(id) => setDeliveryDetailId(id)}
                            />
                          </td>
                        </tr>
                      ) : null}
                    </>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      <WebhookSecretDialog secret={revealedSecret} onClose={() => setRevealedSecret(null)} />
      {deliveryDetailId ? (
        <DeliveryDetailDialog deliveryId={deliveryDetailId} onClose={() => setDeliveryDetailId(null)} />
      ) : null}
    </div>
  );
}

function DeliveriesPanel({
  endpointId,
  onViewDetail,
}: {
  endpointId: string;
  onViewDetail: (deliveryId: string) => void;
}) {
  const { t, language } = useTranslation();
  const toast = useToast();
  const [deliveries, setDeliveries] = useState<WebhookDelivery[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [resendingId, setResendingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await apiFetch<PaginatedWebhookDeliveries>(orgPath(`webhooks/${endpointId}/deliveries`));
      setDeliveries(result.items);
    } catch (err) {
      toast.error(formatApiError(err, t("webhooks.toastActionError")));
      setDeliveries([]);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpointId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleResend(delivery: WebhookDelivery) {
    setResendingId(delivery.id);
    try {
      await apiFetch(orgPath(`webhooks/deliveries/${delivery.id}/resend`), { method: "POST" });
      toast.success(t("webhooks.toastResent"));
      await load();
    } catch (err) {
      toast.error(formatApiError(err, t("webhooks.toastActionError")));
    } finally {
      setResendingId(null);
    }
  }

  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t("webhooks.deliveriesTitle")}
      </h3>
      {loading ? (
        <p className="mt-2 text-sm text-slate-500">{t("webhooks.loading")}</p>
      ) : !deliveries || deliveries.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">{t("webhooks.noDeliveries")}</p>
      ) : (
        <div className="mt-2 overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead>
              <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">{t("webhooks.colDeliveryStatus")}</th>
                <th className="px-3 py-2">{t("webhooks.colDeliveryTrigger")}</th>
                <th className="px-3 py-2">{t("webhooks.colDeliveryResponse")}</th>
                <th className="px-3 py-2">{t("webhooks.colDeliveryAttemptedAt")}</th>
                <th className="px-3 py-2">{t("webhooks.colDeliveryNextRetry")}</th>
                <th className="px-3 py-2 text-right">{t("common.moreActions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {deliveries.map((delivery) => (
                <tr key={delivery.id}>
                  <td className="px-3 py-2">
                    <Badge className={DELIVERY_STATUS_BADGE_CLASS[delivery.status]}>
                      {t(`webhooks.deliveryStatus${delivery.status.charAt(0).toUpperCase()}${delivery.status.slice(1)}`)}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{triggerLabel(t, delivery.trigger)}</td>
                  <td className="px-3 py-2 text-slate-600">
                    {delivery.response_status_code ?? delivery.error_message ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-600">{formatDateTime(delivery.attempted_at, language)}</td>
                  <td className="px-3 py-2 text-slate-600">
                    {delivery.status === "failed" && delivery.next_retry_at
                      ? formatDateTime(delivery.next_retry_at, language)
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      className="text-xs font-medium text-slate-700 underline-offset-2 hover:underline"
                      onClick={() => onViewDetail(delivery.id)}
                    >
                      {t("webhooks.viewDetailAction")}
                    </button>
                    <button
                      type="button"
                      className="ml-3 text-xs font-medium text-slate-700 underline-offset-2 hover:underline disabled:opacity-50"
                      disabled={resendingId === delivery.id}
                      onClick={() => void handleResend(delivery)}
                    >
                      {t("webhooks.resendAction")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DeliveryDetailDialog({ deliveryId, onClose }: { deliveryId: string; onClose: () => void }) {
  const { t, language } = useTranslation();
  const [mounted, setMounted] = useState(false);
  const [detail, setDetail] = useState<WebhookDeliveryDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetch<WebhookDeliveryDetail>(orgPath(`webhooks/deliveries/${deliveryId}`))
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [deliveryId]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!mounted) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex animate-backdrop-in items-center justify-center bg-slate-900/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("webhooks.deliveryDetailTitle")}
        className="max-h-[85vh] w-[calc(100vw-2rem)] max-w-2xl animate-modal-in overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">{t("webhooks.deliveryDetailTitle")}</h2>
          <Button type="button" variant="secondary" size="sm" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>

        {loading || !detail ? (
          <p className="mt-4 text-sm text-slate-500">{t("webhooks.loading")}</p>
        ) : (
          <div className="mt-4 space-y-4 text-sm">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {t("webhooks.detailEventType")}
              </p>
              <p className="mt-1 break-words font-mono text-xs text-slate-800 [overflow-wrap:anywhere]">
                {detail.event.event_type}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {t("webhooks.detailAttemptedAt")}
              </p>
              <p className="mt-1 text-slate-800">{formatDateTime(detail.attempted_at, language)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {t("webhooks.detailResponse")}
              </p>
              <p className="mt-1 break-words text-slate-800 [overflow-wrap:anywhere]">
                {detail.response_status_code ?? "—"} {detail.error_message ? `— ${detail.error_message}` : ""}
              </p>
              {detail.response_body_snippet ? (
                <pre className="mt-1 max-h-40 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                  {detail.response_body_snippet}
                </pre>
              ) : null}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {t("webhooks.detailPayload")}
              </p>
              <pre className="mt-1 max-h-56 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                {JSON.stringify(detail.event.payload, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
