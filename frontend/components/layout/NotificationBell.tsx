"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationId } from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Notification, PaginatedNotificationsResponse } from "@/lib/types";

const PREVIEW_LIMIT = 5;

/** Phase 20 -- a small unread-count bell with a dropdown preview of the
 * current user's most recent in-app notifications (see
 * app.notifications.service.emit_event for how these are generated).
 * Full history + read-all + the email preference toggle live at
 * /settings/notifications; this component is deliberately just a quick
 * glance, refetched once per navigation (see the pathname-triggered
 * refetch pattern AppShell itself already uses for other per-navigation
 * data), not on a polling interval -- this app has no other
 * near-real-time UI anywhere else either. */
export function NotificationBell() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState<Notification[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // orgPath() throws synchronously (before any promise chain begins)
    // if no organization is configured yet -- true briefly during the
    // initial auth check, and in AppShell's own "not authenticated,
    // about to redirect" render. Skip the fetch entirely rather than
    // letting that throw escape the effect.
    if (!getOrganizationId()) {
      setUnreadCount(0);
      setItems(null);
      return;
    }
    let cancelled = false;
    apiFetch<PaginatedNotificationsResponse>(orgPath(`notifications?limit=${PREVIEW_LIMIT}`))
      .then((response) => {
        if (cancelled) return;
        setUnreadCount(response.unread_count);
        setItems(response.items);
      })
      .catch(() => {
        if (!cancelled) {
          setUnreadCount(0);
          setItems(null);
        }
      });
    return () => {
      cancelled = true;
    };
    // Re-runs when the dropdown opens (not just on mount) so a stale
    // count from an earlier page doesn't linger for an entire client-
    // side-routed session -- AppShell itself never unmounts this
    // component between navigations.
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  async function markRead(notification: Notification) {
    if (notification.read_at) return;
    try {
      const updated = await apiFetch<Notification>(
        orgPath(`notifications/${notification.id}/read`),
        { method: "POST" }
      );
      setItems((prev) => (prev ? prev.map((n) => (n.id === updated.id ? updated : n)) : prev));
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch {
      // Best-effort from a preview dropdown -- the full inbox page is
      // the authoritative place to retry a failed mark-read.
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t("notificationBell.label")}
        aria-expanded={open}
        className="relative rounded-lg p-2 text-slate-600 transition hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unreadCount > 0 ? (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="absolute right-0 z-20 mt-2 w-80 max-w-[90vw] rounded-2xl border border-slate-200 bg-white shadow-lg">
          <div className="border-b border-slate-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-900">{t("notificationBell.title")}</h2>
          </div>
          {!items || items.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-slate-500">
              {t("notificationBell.empty")}
            </p>
          ) : (
            <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
              {items.map((notification) => (
                <li
                  key={notification.id}
                  className={`px-4 py-3 ${notification.read_at ? "" : "bg-slate-50"}`}
                >
                  <button
                    type="button"
                    onClick={() => markRead(notification)}
                    className="w-full text-left"
                  >
                    <p className="text-sm font-medium text-slate-900">{notification.title}</p>
                    <p className="mt-0.5 text-xs text-slate-600">{notification.body}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="border-t border-slate-100 px-4 py-2.5">
            <Link
              href="/settings/notifications"
              onClick={() => setOpen(false)}
              className="text-xs font-medium text-slate-700 hover:text-slate-900"
            >
              {t("notificationBell.viewAll")}
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}
