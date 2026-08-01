"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/Skeleton";
import { apiFetch, orgPath } from "@/lib/api";
import { getOrganizationId } from "@/lib/auth-storage";
import { formatRelativeTime } from "@/lib/format-relative-time";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { Notification, PaginatedNotificationsResponse } from "@/lib/types";

const PREVIEW_LIMIT = 5;

/** Phase 20 -- a small unread-count bell with a preview of the current
 * user's most recent in-app notifications (see
 * app.notifications.service.emit_event for how these are generated).
 * Full history + read-all + the email preference toggle live at
 * /settings/notifications; this component is deliberately just a quick
 * glance, refetched once per navigation (see the pathname-triggered
 * refetch pattern AppShell itself already uses for other per-navigation
 * data), not on a polling interval -- this app has no other
 * near-real-time UI anywhere else either.
 *
 * Phase UX4 redesign -- same data, same actions (fetch preview, mark one
 * read, link to the full inbox), new presentation:
 * - Desktop: a floating card (~400px, rounded-2xl, real shadow) instead
 *   of the previous 320px dropdown, with a sticky header/footer around
 *   an internally-scrolling list, relative timestamps, and a real
 *   loading skeleton (previously the empty-state text flashed on every
 *   open while the fetch was in flight, since `items` starts null and
 *   null was indistinguishable from "loaded, and it's empty").
 * - Mobile: a full-width bottom sheet with a backdrop, replacing the
 *   same cramped dropdown that used to render unchanged at any width.
 * One shared content tree drives both -- mobile-first classes position
 * it as a bottom sheet by default, `md:` variants reposition the exact
 * same element as the floating card at wider viewports, rather than
 * rendering two duplicate copies of the list. `md:` (not `sm:`) is
 * deliberate -- it must match AppShell's own breakpoint for swapping
 * the mobile top-bar bell for the desktop sidebar's bell (both
 * `md:hidden`/`md:flex`), since this component always positions itself
 * relative to whichever of those two bell instances is actually
 * visible. The desktop anchor is `left-0`, not `right-0`, because that
 * instance sits inside the narrow (224px) sidebar near its *left* edge
 * -- anchoring the panel's right edge there pushed a 400px panel mostly
 * off the left side of the viewport; anchoring the left edge instead
 * lets it extend rightward into the (much wider) main content area. */
export function NotificationBell() {
  const { t, language } = useTranslation();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState<Notification[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelId = "notification-center-panel";

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
    setLoading(true);
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
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Re-runs when the panel opens (not just on mount) so a stale count
    // from an earlier page doesn't linger for an entire client-side-
    // routed session -- AppShell itself never unmounts this component
    // between navigations.
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

  // Background scroll lock on mobile while the sheet is open -- same
  // pattern AppShell's own off-canvas nav already uses for its bottom/
  // side sheet.
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
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
      // Best-effort from a preview panel -- the full inbox page is the
      // authoritative place to retry a failed mark-read.
    }
  }

  const now = new Date();

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t("notificationBell.label")}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? panelId : undefined}
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
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white ring-2 ring-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        ) : null}
      </button>

      {open ? (
        <>
          {/* Backdrop -- only visually present below md: (bottom-sheet
              context); on desktop the existing click-outside/Escape
              listeners above are what close the floating card. Has its
              own onClick rather than relying on containerRef's outside-
              click check, since this element is itself inside
              containerRef. */}
          <div
            className="fixed inset-0 z-40 animate-backdrop-in bg-slate-900/40 md:hidden"
            onClick={() => setOpen(false)}
            aria-hidden
          />

          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label={t("notificationBell.title")}
            className="fixed inset-x-0 bottom-0 z-50 flex max-h-[80vh] animate-sheet-in flex-col rounded-t-2xl border border-slate-200 bg-white shadow-2xl md:absolute md:inset-x-auto md:bottom-auto md:left-0 md:top-full md:mt-2 md:max-h-[32rem] md:w-[400px] md:max-w-[calc(100vw-2rem)] md:animate-dropdown-in md:rounded-2xl md:border-slate-200 md:shadow-xl md:ring-1 md:ring-black/5"
          >
            {/* Sticky header */}
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div className="flex items-center gap-2.5">
                <h2 className="text-base font-semibold text-slate-900 md:text-sm">
                  {t("notificationBell.title")}
                </h2>
                {unreadCount > 0 ? (
                  <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-900 px-1.5 text-[11px] font-semibold text-white">
                    {unreadCount > 99 ? "99+" : unreadCount}
                  </span>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t("notificationBell.close")}
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  aria-hidden
                >
                  <path d="M18 6 6 18" />
                  <path d="m6 6 12 12" />
                </svg>
              </button>
            </div>

            {/* Internally-scrolling body */}
            <div className="min-h-0 flex-1 overflow-y-auto">
              {loading ? (
                <ul className="divide-y divide-slate-100" aria-hidden>
                  {Array.from({ length: 3 }).map((_, i) => (
                    <li key={i} className="flex items-start gap-3 px-5 py-4">
                      <Skeleton variant="circle" className="h-8 w-8 shrink-0" />
                      <div className="min-w-0 flex-1 space-y-2">
                        <Skeleton className="h-3.5 w-3/4" />
                        <Skeleton className="h-3 w-full" />
                      </div>
                    </li>
                  ))}
                  <span className="sr-only">{t("notificationBell.loading")}</span>
                </ul>
              ) : !items || items.length === 0 ? (
                <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
                  <span className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="22"
                      height="22"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden
                    >
                      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
                    </svg>
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {t("notificationBell.empty")}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {t("notificationBell.emptyDescription")}
                    </p>
                  </div>
                </div>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {items.map((notification) => (
                    <li key={notification.id} className={notification.read_at ? "" : "bg-sky-50/60"}>
                      <button
                        type="button"
                        onClick={() => markRead(notification)}
                        className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-slate-50"
                      >
                        {!notification.read_at ? (
                          <span
                            className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-sky-500"
                            aria-hidden
                          />
                        ) : (
                          <span className="mt-1.5 h-2 w-2 shrink-0" aria-hidden />
                        )}
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium leading-snug text-slate-900">
                            {notification.title}
                          </span>
                          <span className="mt-0.5 block break-words text-sm leading-snug text-slate-600 [overflow-wrap:anywhere]">
                            {notification.body}
                          </span>
                          <span className="mt-1 block text-xs text-slate-400">
                            {formatRelativeTime(notification.created_at, now, language)}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Sticky footer */}
            <div className="shrink-0 border-t border-slate-100 px-5 py-3">
              <Link
                href="/settings/notifications"
                onClick={() => setOpen(false)}
                className="block text-center text-sm font-medium text-slate-700 transition-colors hover:text-slate-900 md:text-left"
              >
                {t("notificationBell.viewAll")}
              </Link>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
