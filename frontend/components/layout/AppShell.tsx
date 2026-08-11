"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { NavIcon } from "@/components/layout/NavIcon";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { useToast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api";
import {
  clearAuthSession,
  EMAIL_VERIFIED_STORAGE_KEY,
  getEmailVerified,
  getOrganizationId,
  getOrganizationName,
  getOrganizationPermissions,
  getPlatformRole,
  getUserEmail,
  isAuthenticated,
  setEmailVerified as cacheEmailVerified,
  updateActiveOrganization,
  updateOrganizationPermissions,
  updatePlatformRole,
} from "@/lib/auth-storage";
import { formatApiError, isRateLimitedError } from "@/lib/format-api-error";
import { useTranslation } from "@/lib/i18n/useTranslation";
import { hasPermission, type Permission } from "@/lib/permissions";
import type { MeResponse, MessageResponse, OrganizationSummary } from "@/lib/types";

type NavLink = { href: string; labelKey: string; permission?: Permission };

const links: NavLink[] = [
  { href: "/dashboard", labelKey: "nav.dashboard" },
  // Permission-gated (unlike every other link here) since it's the one
  // nav entry Phase 16B added behind Permission.dashboard_view -- the
  // backend already enforces this on GET /analytics/kpis; hiding the link
  // client-side just avoids sending a member to a page that would 403.
  { href: "/analytics", labelKey: "nav.analytics", permission: "dashboard.view" },
  { href: "/invoices", labelKey: "nav.invoices" },
  { href: "/quotes", labelKey: "nav.quotes" },
  { href: "/customers", labelKey: "nav.customers" },
  { href: "/products", labelKey: "nav.products" },
  { href: "/assistant", labelKey: "nav.assistant" },
  { href: "/settings", labelKey: "nav.settings" },
];

function isNavActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const { t } = useTranslation();
  const [organizationName, setOrganizationName] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  // Same hydration-safe pattern as organizationName below: empty on first
  // render (server and client agree), then re-read on every navigation.
  const [orgPermissions, setOrgPermissions] = useState<string[]>([]);
  // Hydration-safe default (see getOrganizationName below for the same
  // pattern): assume verified until the first /auth/me response actually
  // says otherwise, so the banner never flashes on a verified account.
  const [emailVerified, setEmailVerifiedState] = useState(true);
  const [isResending, setIsResending] = useState(false);
  // The full membership list -- needed to render a switcher at all (a
  // single-org user just sees their org name, same as before this
  // feature). Populated from the same /auth/me call the email-verified
  // check already makes, rather than a second request.
  const [organizations, setOrganizations] = useState<OrganizationSummary[] | null>(null);
  const [isSwitchingOrg, setIsSwitchingOrg] = useState(false);
  const [platformRole, setPlatformRole] = useState<string | null>(null);
  // Set from the same /auth/me call as everything else above -- /auth/me
  // is deliberately not org-scoped (no require_permission/require_org_
  // member call), so it stays reachable even when the active organization
  // is suspended, unlike every other endpoint this app calls (see
  // app.deps._ensure_organization_active on the backend). This is what
  // lets AppShell detect "the org I'm in got suspended while I was
  // already signed in" instead of every page just 403ing individually.
  const [activeOrgSuspended, setActiveOrgSuspended] = useState(false);

  // Mobile off-canvas nav -- a native <dialog> (via showModal/close) gets
  // focus-trapping, Escape-to-close, and focus-return to the triggering
  // button for free, straight from the browser, with no hand-rolled
  // focus-trap or keydown-listener code needed.
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  // Starts false so the panel's first paint is off-screen (translate-x
  // applied), then flips true one frame later so the browser has two
  // distinct states to interpolate a slide-in transition between --
  // toggling the class immediately on open wouldn't animate at all.
  const [panelVisible, setPanelVisible] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const hamburgerButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }

    let cancelled = false;
    apiFetch<MeResponse>("/auth/me")
      .then((me) => {
        if (cancelled) return;
        setEmailVerifiedState(me.user.email_verified);
        cacheEmailVerified(me.user.email_verified);
        setOrganizations(me.organizations);
        // Keeps the cached permission set for the *active* org current --
        // a role change made by another admin (or in another tab) takes
        // effect here on next navigation, not just on next login.
        const active = me.organizations.find((o) => o.id === getOrganizationId());
        if (active) {
          updateOrganizationPermissions(active.permissions);
          // Same immediate-state-update reasoning as setPlatformRole below:
          // the pathname-keyed effect that also reads this only re-runs on
          // navigation, so without this the nav link gating would stay one
          // /auth/me response behind on the page the user is already on.
          setOrgPermissions(active.permissions);
        } else if (me.organizations.length > 0) {
          // The cached active org is gone from this user's own list --
          // most likely they just removed themselves from it (see
          // app.services.team.remove_member_record's self-removal
          // allowance). Rather than keep every subsequent org-scoped
          // request 403ing against a stale id, silently switch to
          // another org they still belong to and reload, the same way
          // switchOrganization() below does for a deliberate switch.
          const fallback = me.organizations[0];
          updateActiveOrganization({
            organizationId: fallback.id,
            organizationName: fallback.name,
            organizationCurrency: fallback.currency_code,
            organizationLanguage: fallback.language,
            organizationPermissions: fallback.permissions,
          });
          window.location.assign("/dashboard");
          return;
        } else {
          // No organizations left at all -- nothing safe to fall back
          // to, so end the session cleanly rather than leaving the UI
          // pointed at an organization the user no longer belongs to.
          clearAuthSession();
          router.replace("/login");
          return;
        }
        setActiveOrgSuspended(active?.status === "suspended");
        // Same freshness guarantee for the platform-admin entry link --
        // a newly-granted (or revoked) platform role takes effect here on
        // next navigation, not just on next login.
        updatePlatformRole(me.user.platform_role);
        setPlatformRole(me.user.platform_role);
      })
      .catch((err) => {
        if (!cancelled && err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router, pathname]);

  useEffect(() => {
    // Cheap, synchronous re-read on every navigation so a rename saved on
    // /settings shows up in the sidebar without requiring a re-login.
    setOrganizationName(getOrganizationName());
    setEmailVerifiedState(getEmailVerified());
    setUserEmail(getUserEmail());
    setPlatformRole(getPlatformRole());
    setOrgPermissions(getOrganizationPermissions());
  }, [pathname]);

  useEffect(() => {
    // Cross-tab sync: if verification completes on /verify-email in a
    // *different* tab of this same browser, that page writes the new value
    // to localStorage, which fires this `storage` event here — so the
    // banner disappears in this tab immediately, with no navigation or
    // manual refresh needed in this tab at all.
    function onStorage(e: StorageEvent) {
      if (e.key === EMAIL_VERIFIED_STORAGE_KEY) {
        setEmailVerifiedState(getEmailVerified());
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // Syncs React state from the dialog's own native 'close' event -- this
  // fires whether the dialog closed via our button, a backdrop click, or
  // the browser's built-in Escape handling, so this is the single place
  // mobileNavOpen ever gets set back to false.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    function handleClose() {
      setMobileNavOpen(false);
    }
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  // Flips one frame after open so the panel's transform transition has a
  // "before" state to animate from (see panelVisible's declaration).
  useEffect(() => {
    if (!mobileNavOpen) {
      setPanelVisible(false);
      return;
    }
    const raf = requestAnimationFrame(() => setPanelVisible(true));
    return () => cancelAnimationFrame(raf);
  }, [mobileNavOpen]);

  // Background scroll lock while the panel is open -- showModal() already
  // blocks interaction with the rest of the page, but doesn't reliably
  // prevent background scroll (e.g. via touch) in every browser.
  useEffect(() => {
    if (!mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileNavOpen]);

  // Closes the panel on navigation -- a link tap inside it should never
  // leave it open underneath the newly-loaded page.
  useEffect(() => {
    dialogRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  function openMobileNav() {
    dialogRef.current?.showModal();
    setMobileNavOpen(true);
  }

  function closeMobileNav() {
    dialogRef.current?.close();
    // A native <dialog> is supposed to restore focus to whatever had it
    // before showModal() on its own, but that's only reliable when the
    // dialog was opened via a genuine, trusted user gesture -- explicitly
    // re-focusing the trigger here guarantees it regardless.
    hamburgerButtonRef.current?.focus();
  }

  function logout() {
    clearAuthSession();
    router.replace("/login");
  }

  function switchOrganization(organizationId: string) {
    if (isSwitchingOrg || organizationId === getOrganizationId()) return;
    const target = organizations?.find((o) => o.id === organizationId);
    if (!target) return;
    setIsSwitchingOrg(true);
    updateActiveOrganization({
      organizationId: target.id,
      organizationName: target.name,
      organizationCurrency: target.currency_code,
      organizationLanguage: target.language,
      organizationPermissions: target.permissions,
    });
    // A full reload, not a client-side navigation -- every already-loaded
    // page's React state (invoice lists, dashboard totals, etc.) was
    // fetched for the *previous* organization and has no reason to
    // reactively refetch just because localStorage changed underneath it.
    window.location.assign("/dashboard");
  }

  async function resendVerification() {
    if (isResending) return;
    setIsResending(true);
    try {
      const result = await apiFetch<MessageResponse>("/auth/resend-verification", {
        method: "POST",
      });
      toast.success(result.message || t("emailBanner.resendSuccess"));
    } catch (err) {
      toast.error(
        isRateLimitedError(err)
          ? t("errors.rateLimitedVerification")
          : formatApiError(err, t("emailBanner.resendError"))
      );
    } finally {
      setIsResending(false);
    }
  }

  // Shared between the always-visible desktop sidebar and the mobile
  // off-canvas panel below -- one source of markup, rendered twice (once
  // per breakpoint's container), rather than hand-maintaining two copies.
  // idPrefix keeps the two simultaneously-present <select> instances'
  // DOM ids unique.
  function renderNavContent(idPrefix: string, onNavigate?: () => void) {
    return (
      <>
        {/* The organization sits directly under the wordmark as secondary
            information -- no divider between them, so brand + org read as
            one block, with the single divider below separating that block
            from the navigation. `truncate`/`min-w-0` keep a long
            organization name from ever widening the sidebar. */}
        {organizations && organizations.length > 1 ? (
          <div className="px-3 pb-3">
            <label htmlFor={`${idPrefix}-org-switcher`} className="sr-only">
              {t("nav.switchOrganization")}
            </label>
            <select
              id={`${idPrefix}-org-switcher`}
              value={getOrganizationId() ?? ""}
              onChange={(e) => switchOrganization(e.target.value)}
              disabled={isSwitchingOrg}
              className="w-full truncate rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm font-medium text-slate-700 outline-none ring-slate-400 focus:ring-2 disabled:opacity-60"
            >
              {organizations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>
        ) : organizationName ? (
          <div className="px-3 pb-3">
            <Link
              href="/settings"
              onClick={onNavigate}
              className="block truncate rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-surface-muted hover:text-slate-900"
            >
              {organizationName}
            </Link>
          </div>
        ) : null}
        <div className="border-t border-slate-100" />
        {/* px-3 matches the footer's own horizontal padding so the nav
            items, the org row and the footer all sit on one vertical
            edge -- the rows themselves are inset by their own px-3, which
            is what makes the active pill look aligned rather than
            flush-left against the border. */}
        <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-4">
          {links
            .filter((item) => !item.permission || hasPermission({ permissions: orgPermissions }, item.permission))
            .map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                // Subtle active state: a soft filled pill, slightly
                // stronger text and a full-opacity icon -- no heavy left
                // border, no shadow, no saturated colour. The icon
                // carries most of the state change, which is what keeps
                // it feeling calm at a glance.
                className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-slate-100 font-semibold text-slate-900"
                    : "font-medium text-slate-600 hover:bg-surface-muted hover:text-slate-900"
                }`}
              >
                <NavIcon
                  href={item.href}
                  className={`shrink-0 transition-colors ${
                    active ? "text-slate-900" : "text-slate-400 group-hover:text-slate-600"
                  }`}
                />
                <span className="truncate">{t(item.labelKey)}</span>
              </Link>
            );
          })}
        </nav>
        {/* mt-auto pins this to the bottom of the flex column (the nav
            above is flex-1), which is what visually separates the user
            from the navigation without any absolute positioning. */}
        <div className="mt-auto border-t border-slate-200 px-3 py-3">
          {userEmail ? (
            <div className="mb-2 flex items-center gap-2.5 px-1">
              {/* Initial derived from the email already in the session --
                  no new data, no avatar upload, no request. */}
              <span
                aria-hidden
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold uppercase text-slate-600"
              >
                {userEmail.charAt(0)}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-800">{userEmail}</p>
                {organizationName ? (
                  <p className="truncate text-xs text-slate-500">{organizationName}</p>
                ) : null}
              </div>
            </div>
          ) : null}
          {platformRole ? (
            <Link
              href="/admin"
              onClick={onNavigate}
              className="mb-1.5 block w-full rounded-lg px-3 py-1.5 text-center text-xs font-medium text-slate-600 transition-colors hover:bg-surface-muted hover:text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
            >
              {t("adminNav.entryLink")}
            </Link>
          ) : null}
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-surface-muted hover:text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
          >
            {t("nav.logout")}
          </button>
        </div>
      </>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      {/* Mobile top bar -- the desktop sidebar below is hidden entirely
          below md, replaced by this bar plus the off-canvas panel. */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <Link href="/dashboard" className="text-lg font-semibold text-slate-900">
          Invoicing
        </Link>
        <div className="flex items-center gap-1">
          <NotificationBell />
          <button
            ref={hamburgerButtonRef}
            type="button"
            onClick={openMobileNav}
            aria-label={t("nav.openMenu")}
            className="rounded-lg p-2 text-slate-700 hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden
            >
              <path d="M3 6h18M3 12h18M3 18h18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile off-canvas panel. A native <dialog> gets focus-trapping,
          Escape-to-close, and focus-return to the trigger button straight
          from the browser -- no hand-rolled equivalents needed. Styled as
          a left-edge sliding drawer rather than the browser's default
          centered box. */}
      <dialog
        ref={dialogRef}
        aria-label={t("nav.mobileMenuLabel")}
        onClick={(e) => {
          // A click that lands on the dialog element itself (not a
          // descendant) is a click on the ::backdrop -- see MDN's
          // documented pattern for click-outside-to-close on <dialog>.
          if (e.target === dialogRef.current) closeMobileNav();
        }}
        className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-72 max-w-[85%] border-0 bg-transparent p-0 backdrop:bg-slate-900/40 md:hidden"
      >
        <div
          className={`flex h-full flex-col bg-white shadow-xl transition-transform duration-200 motion-reduce:transition-none ${
            panelVisible ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-4">
            <span className="truncate text-[15px] font-semibold tracking-tight text-slate-900">Invoicing</span>
            <button
              type="button"
              onClick={closeMobileNav}
              aria-label={t("nav.closeMenu")}
              className="rounded-lg p-2 text-slate-700 hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
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
                aria-hidden
              >
                <path d="M18 6 6 18" />
                <path d="m6 6 12 12" />
              </svg>
            </button>
          </div>
          <div className="flex flex-1 flex-col overflow-y-auto">
            {renderNavContent("mobile", closeMobileNav)}
          </div>
        </div>
      </dialog>

      {/* Desktop sidebar -- unchanged in substance from before this pass,
          just now hidden below md instead of also rendering (differently
          styled) on mobile. */}
      {/* Width unchanged at md:w-56 -- the previous full-width pass
          established that this leaves the right amount to the content,
          so nothing here reclaims horizontal space from the page. */}
      {/* sticky + h-dvh: without it the aside is a plain flex child that
          stretches to the full document height, so `mt-auto` pushed the
          user footer thousands of pixels down on any long page. Pinning it
          to the viewport keeps nav and footer permanently in view and lets
          the nav scroll on its own when the list outgrows short screens. */}
      <aside className="hidden shrink-0 flex-col border-slate-200 bg-white md:sticky md:top-0 md:flex md:h-dvh md:w-56 md:border-r">
        {/* px-4 here vs px-3 on the rows below is deliberate: the rows
            have their own px-3 inset, so this lines the wordmark up with
            the nav labels rather than with the pill edges. */}
        <div className="flex items-center justify-between gap-2 px-4 pb-3 pt-5">
          <Link
            href="/dashboard"
            className="truncate text-[15px] font-semibold tracking-tight text-slate-900"
          >
            Invoicing
          </Link>
          <NotificationBell />
        </div>
        {renderNavContent("desktop")}
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-6 md:p-8">
        {activeOrgSuspended ? (
          <div
            role="status"
            className="mx-auto mt-12 max-w-md rounded-2xl border border-red-200 bg-red-50 p-6 text-center"
          >
            <h1 className="text-base font-semibold text-red-900">{t("orgSuspendedNotice.title")}</h1>
            <p className="mt-2 text-sm text-red-800">{t("orgSuspendedNotice.description")}</p>
          </div>
        ) : (
          <>
            {!emailVerified ? (
              <div
                role="status"
                className="mb-4 flex flex-col items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between"
              >
                <p>{t("emailBanner.message")}</p>
                <button
                  type="button"
                  onClick={() => void resendVerification()}
                  disabled={isResending}
                  className="shrink-0 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isResending ? t("emailBanner.resendSending") : t("emailBanner.resendAction")}
                </button>
              </div>
            ) : null}
            {children}
          </>
        )}
      </main>
    </div>
  );
}
