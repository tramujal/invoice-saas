"use client";

import { useCallback, useEffect, useState } from "react";

import { SettingsSubNav } from "@/components/settings/SettingsSubNav";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/toast";
import { apiFetch, orgPath } from "@/lib/api";
import { formatApiError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type {
  Notification,
  NotificationPreference,
  PaginatedNotificationsResponse,
} from "@/lib/types";

const PAGE_SIZE = 20;

export default function NotificationsSettingsPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [notifications, setNotifications] = useState<Notification[] | null>(null);
  const [total, setTotal] = useState(0);
  const [unreadCount, setUnreadCount] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [preference, setPreference] = useState<NotificationPreference | null>(null);
  const [savingPreference, setSavingPreference] = useState(false);

  const load = useCallback(async (currentOffset: number) => {
    setLoading(true);
    setError(false);
    try {
      const response = await apiFetch<PaginatedNotificationsResponse>(
        orgPath(`notifications?limit=${PAGE_SIZE}&offset=${currentOffset}`)
      );
      setNotifications(response.items);
      setTotal(response.total);
      setUnreadCount(response.unread_count);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(offset);
  }, [load, offset]);

  useEffect(() => {
    apiFetch<NotificationPreference>(orgPath("notification-preferences"))
      .then(setPreference)
      .catch(() => setPreference(null));
  }, []);

  async function markRead(notification: Notification) {
    if (notification.read_at) return;
    try {
      const updated = await apiFetch<Notification>(
        orgPath(`notifications/${notification.id}/read`),
        { method: "POST" }
      );
      setNotifications((prev) =>
        prev ? prev.map((n) => (n.id === updated.id ? updated : n)) : prev
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch (err) {
      toast.error(formatApiError(err, t("notificationsPage.markReadError")));
    }
  }

  async function markAllRead() {
    if (markingAll || unreadCount === 0) return;
    setMarkingAll(true);
    try {
      const response = await apiFetch<PaginatedNotificationsResponse>(
        orgPath("notifications/read-all"),
        { method: "POST" }
      );
      setNotifications(response.items);
      setTotal(response.total);
      setUnreadCount(response.unread_count);
    } catch (err) {
      toast.error(formatApiError(err, t("notificationsPage.markAllReadError")));
    } finally {
      setMarkingAll(false);
    }
  }

  async function toggleEmailPreference(enabled: boolean) {
    setSavingPreference(true);
    try {
      const updated = await apiFetch<NotificationPreference>(
        orgPath("notification-preferences"),
        { method: "PATCH", body: JSON.stringify({ email_enabled: enabled }) }
      );
      setPreference(updated);
    } catch (err) {
      toast.error(formatApiError(err, t("notificationsPage.preferenceError")));
    } finally {
      setSavingPreference(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("notificationsPage.title")}
        subtitle={t("notificationsPage.subtitle")}
      />
      <SettingsSubNav />

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              {t("notificationsPage.emailPreferenceTitle")}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              {t("notificationsPage.emailPreferenceDescription")}
            </p>
          </div>
          <label className="flex shrink-0 items-center gap-2 text-sm font-medium text-slate-700">
            <input
              type="checkbox"
              checked={preference?.email_enabled ?? true}
              disabled={savingPreference || preference === null}
              onChange={(e) => toggleEmailPreference(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400"
            />
            {t("notificationsPage.emailPreferenceToggleLabel")}
          </label>
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-900">
            {t("notificationsPage.inboxTitle")}
            {unreadCount > 0 ? (
              <Badge className="ml-2 bg-slate-900 text-white ring-slate-900">{unreadCount}</Badge>
            ) : null}
          </h2>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={markAllRead}
            disabled={markingAll || unreadCount === 0}
          >
            {markingAll ? t("notificationsPage.markingAll") : t("notificationsPage.markAllRead")}
          </Button>
        </div>

        {loading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-14 animate-pulse rounded-xl bg-slate-100" aria-hidden />
            ))}
          </div>
        ) : error ? (
          <div className="px-5 py-4 text-sm text-red-800" role="alert">
            {t("notificationsPage.loadError")}
          </div>
        ) : !notifications || notifications.length === 0 ? (
          <EmptyState
            title={t("notificationsPage.emptyTitle")}
            description={t("notificationsPage.emptyDescription")}
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {notifications.map((notification) => (
              <li
                key={notification.id}
                className={`flex items-start justify-between gap-4 px-5 py-4 ${
                  notification.read_at ? "" : "bg-slate-50"
                }`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900">{notification.title}</p>
                  <p className="mt-0.5 text-sm text-slate-600">{notification.body}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {new Date(notification.created_at).toLocaleString()}
                  </p>
                </div>
                {notification.read_at ? null : (
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="shrink-0"
                    onClick={() => markRead(notification)}
                  >
                    {t("notificationsPage.markRead")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        {total > PAGE_SIZE ? (
          <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              {t("notificationsPage.previous")}
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              {t("notificationsPage.next")}
            </Button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
