"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { NavIcon } from "@/components/layout/NavIcon";
import { apiFetch, ApiError } from "@/lib/api";
import {
  clearAuthSession,
  getAuthToken,
  getPlatformRole,
  getUserEmail,
  updatePlatformRole,
} from "@/lib/auth-storage";
import { useTranslation } from "@/lib/i18n/useTranslation";
import type { MeResponse } from "@/lib/types";

const links = [
  { href: "/admin", labelKey: "adminNav.dashboard" },
  { href: "/admin/organizations", labelKey: "adminNav.organizations" },
  { href: "/admin/plans", labelKey: "adminNav.plans" },
  { href: "/admin/subscriptions", labelKey: "adminNav.subscriptions" },
  { href: "/admin/users", labelKey: "adminNav.users" },
  { href: "/admin/system-health", labelKey: "adminNav.systemHealth" },
  { href: "/admin/jobs", labelKey: "adminNav.jobs" },
  { href: "/admin/audit-log", labelKey: "adminNav.auditLog" },
  { href: "/admin/settings", labelKey: "adminNav.settings" },
] as const;

function isNavActive(pathname: string, href: string): boolean {
  // The root link (/admin, the Dashboard) must only match exactly --
  // every other admin route also starts with "/admin/", which would
  // otherwise keep "Dashboard" highlighted everywhere.
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The platform-administration equivalent of AppShell -- a completely
 * separate shell, deliberately not reusing AppShell, since that
 * component's auth gate (isAuthenticated()) and org switcher both
 * require an active organization, which a platform-admin-only account
 * (zero organization memberships) never has. See lib/auth-storage.ts's
 * isPlatformAdminAuthenticated()/getPlatformRole() for the parallel,
 * org-independent authorization axis this shell gates on. */
export function PlatformAdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [hasOrganizations, setHasOrganizations] = useState(false);
  const [ready, setReady] = useState(false);

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [panelVisible, setPanelVisible] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const hamburgerButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // No token at all -- not signed in to anything.
    if (!getAuthToken()) {
      router.replace("/login");
      return;
    }
    // Signed in, but no cached platform role -- an ordinary organization
    // user landed here directly; send them to their own dashboard rather
    // than bouncing an already-authenticated person to /login.
    if (!getPlatformRole()) {
      router.replace("/dashboard");
      return;
    }

    let cancelled = false;
    apiFetch<MeResponse>("/auth/me")
      .then((me) => {
        if (cancelled) return;
        // Keeps the cached role current, including a revocation that
        // happened mid-session (see updatePlatformRole's own docstring).
        updatePlatformRole(me.user.platform_role);
        if (!me.user.platform_role) {
          router.replace("/dashboard");
          return;
        }
        setUserEmail(me.user.email);
        setHasOrganizations(me.organizations.length > 0);
        setReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router, pathname]);

  useEffect(() => {
    setUserEmail(getUserEmail());
  }, [pathname]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    function handleClose() {
      setMobileNavOpen(false);
    }
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  useEffect(() => {
    if (!mobileNavOpen) {
      setPanelVisible(false);
      return;
    }
    const raf = requestAnimationFrame(() => setPanelVisible(true));
    return () => cancelAnimationFrame(raf);
  }, [mobileNavOpen]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileNavOpen]);

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
    hamburgerButtonRef.current?.focus();
  }

  function logout() {
    clearAuthSession();
    router.replace("/login");
  }

  function renderNavContent(onNavigate?: () => void) {
    return (
      <>
        {/* The admin badge stays exactly as-is -- it is the one thing that
            must keep this context visually distinct from the tenant app.
            Only its surrounding spacing is aligned with AppShell's. */}
        <div className="px-3 pb-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-2.5 py-1 text-xs font-semibold text-white">
            {t("adminNav.badge")}
          </span>
        </div>
        <div className="border-t border-slate-100" />
        {/* Identical row/active-state treatment to AppShell so the two
            sidebars read as one product -- see that component for the
            rationale behind the pill and the icon colour states. */}
        <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-4">
          {links.map((item) => {
            const active = isNavActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
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
        <div className="mt-auto border-t border-slate-200 px-3 py-3">
          {userEmail ? (
            <div className="mb-2 flex items-center gap-2.5 px-1">
              <span
                aria-hidden
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold uppercase text-slate-600"
              >
                {userEmail.charAt(0)}
              </span>
              <p className="min-w-0 truncate text-sm font-medium text-slate-800">{userEmail}</p>
            </div>
          ) : null}
          {hasOrganizations ? (
            <Link
              href="/dashboard"
              onClick={onNavigate}
              className="mb-1.5 block w-full rounded-lg px-3 py-1.5 text-center text-xs font-medium text-slate-600 transition-colors hover:bg-surface-muted hover:text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400"
            >
              {t("adminNav.returnToOrganization")}
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

  // The cached platform_role (read synchronously above, before /auth/me
  // even resolves) is NEVER treated as authoritative -- it only decides
  // where to redirect a visitor who isn't a platform admin at all. Actual
  // admin chrome/content, and the child page's own data fetch, are gated
  // exclusively on `ready`, which only becomes true after the live
  // /auth/me response confirms a platform_role. `children` is not
  // rendered into the tree below this line, so the child page component
  // never mounts -- and therefore never fires its own /admin/* fetch --
  // until that server round-trip has completed. Every /admin/* endpoint
  // still independently re-checks require_platform_permission server-side
  // regardless of anything the frontend does; this gate is a UX nicety
  // (avoiding a flash of admin chrome for a visitor about to be
  // redirected), never a security boundary.
  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-surface" role="status">
        <span className="sr-only">{t("adminNav.verifyingAccess")}</span>
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" aria-hidden />
      </div>
    );
  }

  // The "Invoicing" wordmark always represents the *product*, not the
  // current admin module -- clicking it returns to the tenant app the
  // same way it would from anywhere in AppShell. The one edge case: a
  // platform-admin-only account with zero organization memberships has
  // nowhere in the tenant app to land (AppShell's isAuthenticated() gate
  // requires an active organization id), so the logo stays a same-page,
  // no-op link to /admin for that account rather than bouncing them to a
  // broken/blank destination.
  const logoHref = hasOrganizations ? "/dashboard" : "/admin";

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <div className="flex items-center gap-2">
          <Link
            href={logoHref}
            className="truncate text-[15px] font-semibold tracking-tight text-slate-900"
          >
            Invoicing
          </Link>
          <span className="inline-flex items-center rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-semibold text-white">
            {t("adminNav.badge")}
          </span>
        </div>
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

      <dialog
        ref={dialogRef}
        aria-label={t("nav.mobileMenuLabel")}
        onClick={(e) => {
          if (e.target === dialogRef.current) closeMobileNav();
        }}
        className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-72 max-w-[85%] border-0 bg-transparent p-0 backdrop:bg-slate-900/40 md:hidden"
      >
        <div
          className={`flex h-full flex-col bg-white shadow-xl transition-transform duration-200 motion-reduce:transition-none ${
            panelVisible ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-4">
            <span className="text-lg font-semibold text-slate-900">{t("adminNav.badge")}</span>
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
          <div className="flex flex-1 flex-col overflow-y-auto">{renderNavContent(closeMobileNav)}</div>
        </div>
      </dialog>

      {/* Pinned to the viewport for the same reason as the tenant shell:
          otherwise the aside stretches to the full document height and the
          user footer ends up below the fold on long admin tables. */}
      <aside className="hidden shrink-0 flex-col border-slate-200 bg-white md:sticky md:top-0 md:flex md:h-dvh md:w-56 md:border-r">
        <div className="px-4 pb-3 pt-5">
          <Link href={logoHref} className="text-lg font-semibold text-slate-900">
            Invoicing
          </Link>
        </div>
        {renderNavContent()}
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-6 md:p-8">{children}</main>
    </div>
  );
}
